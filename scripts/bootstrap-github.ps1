#requires -Version 5.1
<#
.SYNOPSIS
    按 scripts/github/plan.json 同步 GitHub 的 Label、Milestone 与 Issue，可选创建 PR。

.DESCRIPTION
    幂等脚本：重复执行不会产生重复的 Label、Milestone 或 Issue。
    令牌从 Git 凭据管理器读取（与 git push 使用同一凭据），不接受命令行明文令牌。
    兼容 Windows PowerShell 5.1 与 PowerShell 7。

.PARAMETER Owner
    仓库所有者，默认 Nev3r1ove9y0rmyX。

.PARAMETER Repository
    仓库名，默认 NIS。

.PARAMETER PlanPath
    计划文件路径，默认 scripts/github/plan.json。

.PARAMETER CreatePr
    额外创建当前分支 -> develop 的 PR（已存在则跳过）。

.PARAMETER SkipProject
    跳过 GitHub Project 看板创建。

.PARAMETER DryRun
    只校验计划文件并打印，不访问 GitHub。

.EXAMPLE
    powershell -File scripts/bootstrap-github.ps1
    # 只看会做什么，不真正写：
    powershell -File scripts/bootstrap-github.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [string]$Owner = "Nev3r1ove9y0rmyX",
    [string]$Repository = "NIS",
    [string]$PlanPath = "",
    [switch]$CreatePr,
    [switch]$SkipProject,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# $PSScriptRoot 在 param 默认值里不保证可用（PowerShell 5.1），这里显式解析。
if ([string]::IsNullOrWhiteSpace($PlanPath)) {
    $PlanPath = Join-Path $PSScriptRoot "github/plan.json"
}

# Windows PowerShell 5.1 默认可能不启用 TLS 1.2，api.github.com 需要它。
try {
    [Net.ServicePointManager]::SecurityProtocol = `
        [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
}
catch {
    Write-Verbose "无法设置 TLS 1.2，继续尝试。"
}

function Get-GitHubToken {
    $lines = ("protocol=https`nhost=github.com`n`n" | git credential fill) 2>$null
    if ($LASTEXITCODE -ne 0) { throw "无法从 Git 凭据管理器读取 GitHub 凭据。" }
    foreach ($line in $lines) {
        if ($line -match '^password=(.+)$') { return $Matches[1] }
    }
    throw "凭据中没有 password 字段，请先完成一次 git push 或 gh auth login。"
}

$token = Get-GitHubToken
$headers = @{
    Authorization          = "Bearer $token"
    Accept                 = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent"           = "NIS-bootstrap"
}
$api = "https://api.github.com/repos/$Owner/$Repository"
$warnings = New-Object 'System.Collections.Generic.List[string]'

function ConvertTo-Utf8Json {
    param($Value, [int]$Depth = 10)
    $json = $Value | ConvertTo-Json -Depth $Depth
    # 显式转成 UTF-8 字节，避免 Windows PowerShell 5.1 按本地代码页发送中文。
    return , ([System.Text.Encoding]::UTF8.GetBytes($json))
}

function Invoke-GitHub {
    param(
        [string]$Method = "GET",
        [string]$Uri,
        $Body
    )
    $params = @{ Method = $Method; Headers = $headers; Uri = $Uri }
    if ($null -ne $Body) {
        $params.Body = ConvertTo-Utf8Json -Value $Body
        $params.ContentType = "application/json; charset=utf-8"
    }
    return Invoke-RestMethod @params
}

function Invoke-GraphQL {
    param([string]$Query, [hashtable]$Variables)
    $payload = @{ query = $Query; variables = $Variables }
    $response = Invoke-RestMethod -Method Post -Headers $headers `
        -Uri "https://api.github.com/graphql" `
        -Body (ConvertTo-Utf8Json -Value $payload) -ContentType "application/json; charset=utf-8"
    if ($response.errors) {
        throw ($response.errors | ForEach-Object { $_.message } | Out-String)
    }
    return $response.data
}

function Get-AllPages {
    param([string]$Uri)
    $items = @()
    $page = 1
    while ($true) {
        $separator = if ($Uri.Contains("?")) { "&" } else { "?" }
        $batch = @(Invoke-GitHub -Uri "$Uri${separator}per_page=100&page=$page")
        $items += $batch
        if ($batch.Count -lt 100) { break }
        $page++
    }
    return $items
}

# ---------------- 读取计划 ----------------

if (-not (Test-Path $PlanPath)) { throw "找不到计划文件：$PlanPath" }
$plan = Get-Content -Raw -Encoding utf8 $PlanPath | ConvertFrom-Json
Write-Output "计划文件：$PlanPath"
Write-Output ("  标签 {0} 个 / 里程碑 {1} 个 / Issue {2} 个" -f $plan.labels.Count, $plan.milestones.Count, $plan.issues.Count)

if ($DryRun) {
    Write-Output "[DryRun] 仅检查计划文件，不访问 GitHub。"
    foreach ($issue in $plan.issues) {
        Write-Output ("  - [{0}] {1} -> {2}" -f $issue.state, $issue.title, $issue.milestone)
    }
    return
}

# ---------------- 标签 ----------------

$existingLabels = Get-AllPages -Uri "$api/labels"
$labelIndex = @{}
foreach ($label in $existingLabels) { $labelIndex[$label.name] = $label }

$createdLabels = 0
$updatedLabels = 0
foreach ($spec in $plan.labels) {
    if ($labelIndex.ContainsKey($spec.name)) {
        $current = $labelIndex[$spec.name]
        if ($current.color -ne $spec.color -or $current.description -ne $spec.description) {
            Invoke-GitHub -Method Patch -Uri "$api/labels/$([uri]::EscapeDataString($spec.name))" `
                -Body @{ color = $spec.color; description = $spec.description } | Out-Null
            $updatedLabels++
        }
        continue
    }
    Invoke-GitHub -Method Post -Uri "$api/labels" `
        -Body @{ name = $spec.name; color = $spec.color; description = $spec.description } | Out-Null
    $createdLabels++
}
Write-Output "标签：新建 $createdLabels，更新 $updatedLabels，已存在 $($plan.labels.Count - $createdLabels - $updatedLabels)"

# ---------------- 里程碑 ----------------

$existingMilestones = Get-AllPages -Uri "$api/milestones?state=all"
$milestoneIndex = @{}
foreach ($milestone in $existingMilestones) { $milestoneIndex[$milestone.title] = $milestone }

$createdMilestones = 0
foreach ($spec in $plan.milestones) {
    if ($milestoneIndex.ContainsKey($spec.title)) { continue }
    $created = Invoke-GitHub -Method Post -Uri "$api/milestones" `
        -Body @{ title = $spec.title; description = $spec.description }
    $milestoneIndex[$spec.title] = $created
    $createdMilestones++
}
Write-Output "里程碑：新建 $createdMilestones，已存在 $($plan.milestones.Count - $createdMilestones)"

# ---------------- Issue ----------------

$existingIssues = Get-AllPages -Uri "$api/issues?state=all"
$issueIndex = @{}
foreach ($issue in $existingIssues) {
    if ($issue.pull_request) { continue }
    $issueIndex[$issue.title] = $issue
}

$createdIssues = 0
$closedIssues = 0
$issueNumbers = @{}
foreach ($spec in $plan.issues) {
    if (-not $milestoneIndex.ContainsKey($spec.milestone)) {
        $warnings.Add("Issue「$($spec.title)」的里程碑 $($spec.milestone) 不存在，已跳过。")
        continue
    }
    $milestoneNumber = $milestoneIndex[$spec.milestone].number

    if ($issueIndex.ContainsKey($spec.title)) {
        $issue = $issueIndex[$spec.title]
    }
    else {
        $issue = Invoke-GitHub -Method Post -Uri "$api/issues" -Body @{
            title     = $spec.title
            body      = $spec.body
            labels    = @($spec.labels)
            milestone = $milestoneNumber
        }
        $issueIndex[$spec.title] = $issue
        $createdIssues++
        Write-Output ("  新建 Issue #{0} {1}" -f $issue.number, $spec.title)
    }

    $issueNumbers[$spec.title] = $issue.number

    if ($spec.state -eq "closed" -and $issue.state -ne "closed") {
        Invoke-GitHub -Method Patch -Uri "$api/issues/$($issue.number)" `
            -Body @{ state = "closed"; state_reason = "completed" } | Out-Null
        $closedIssues++
        Write-Output ("  关闭 Issue #{0}（已完成）" -f $issue.number)
    }
}
Write-Output "Issue：新建 $createdIssues，关闭 $closedIssues，总计 $($plan.issues.Count)"

# ---------------- Project 看板（尽力而为）----------------

function New-ProjectBoard {
    $boardName = "NIS 协同调度信息系统"
    try {
        $ownerData = Invoke-GraphQL -Query @'
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) { owner { id login } }
}
'@ -Variables @{ owner = $Owner; name = $Repository }
        $ownerId = $ownerData.repository.owner.id

        $existing = Invoke-GraphQL -Query @'
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    owner {
      ... on ProjectV2Owner {
        projectsV2(first: 20) { nodes { id title number } }
      }
    }
  }
}
'@ -Variables @{ owner = $Owner; name = $Repository }
        $found = $existing.repository.owner.projectsV2.nodes | Where-Object { $_.title -eq $boardName } | Select-Object -First 1

        if ($found) {
            $projectId = $found.id
            $projectNumber = $found.number
            Write-Output "看板已存在：#$projectNumber（$boardName）"
        }
        else {
            $created = Invoke-GraphQL -Query @'
mutation($ownerId: ID!, $title: String!) {
  createProjectV2(input: { ownerId: $ownerId, title: $title }) {
    projectV2 { id number url }
  }
}
'@ -Variables @{ ownerId = $ownerId; title = $boardName }
            $projectId = $created.createProjectV2.projectV2.id
            $projectNumber = $created.createProjectV2.projectV2.number
            Write-Output ("看板已创建：{0}" -f $created.createProjectV2.projectV2.url)
        }

        # 状态字段：Backlog / Ready / In Progress / Review / Blocked / Done
        $statusOptions = @("Backlog", "Ready", "In Progress", "Review", "Blocked", "Done")
        $fieldId = $null
        try {
            $fields = Invoke-GraphQL -Query @'
query($projectId: ID!) {
  node(id: $projectId) {
    ... on ProjectV2 {
      fields(first: 30) {
        nodes {
          ... on ProjectV2SingleSelectField { id name options { id name } }
        }
      }
    }
  }
}
'@ -Variables @{ projectId = $projectId }
            $status = $fields.node.fields.nodes | Where-Object { $_.name -eq "Status" } | Select-Object -First 1
            if (-not $status) {
                $field = Invoke-GraphQL -Query @'
mutation($projectId: ID!, $name: String!, $options: [ProjectV2SingleSelectFieldOptionInput!]!) {
  createProjectV2Field(input: {
    projectId: $projectId, dataType: SINGLE_SELECT, name: $name, singleSelectOptions: $options
  }) {
    projectV2Field { ... on ProjectV2SingleSelectField { id name options { id name } } }
  }
}
'@ -Variables @{
                    projectId = $projectId
                    name      = "Status"
                    options   = @($statusOptions | ForEach-Object { @{ name = $_; color = "GRAY"; description = "" } })
                }
                $status = $field.createProjectV2Field.projectV2Field
            }
            $fieldId = $status.id
            $optionIndex = @{}
            foreach ($option in $status.options) { $optionIndex[$option.name] = $option.id }
        }
        catch {
            $warnings.Add("创建 Status 字段失败（可能缺少 project 权限）：$($_.Exception.Message)")
        }

        $added = 0
        foreach ($spec in $plan.issues) {
            $number = $issueNumbers[$spec.title]
            if (-not $number) { continue }
            $node = (Invoke-GitHub -Uri "$api/issues/$number").node_id
            $item = Invoke-GraphQL -Query @'
mutation($projectId: ID!, $contentId: ID!) {
  addProjectV2ItemById(input: { projectId: $projectId, contentId: $contentId }) {
    item { id }
  }
}
'@ -Variables @{ projectId = $projectId; contentId = $node }
            $added++

            if ($fieldId -and $optionIndex.Count -gt 0) {
                $target = if ($spec.state -eq "closed") { "Done" } else { "Backlog" }
                if ($optionIndex.ContainsKey($target)) {
                    try {
                        Invoke-GraphQL -Query @'
mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
  updateProjectV2ItemFieldValue(input: {
    projectId: $projectId, itemId: $itemId, fieldId: $fieldId,
    value: { singleSelectOptionId: $optionId }
  }) { projectV2Item { id } }
}
'@ -Variables @{
                            projectId = $projectId
                            itemId    = $item.addProjectV2ItemById.item.id
                            fieldId   = $fieldId
                            optionId  = $optionIndex[$target]
                        } | Out-Null
                    }
                    catch {
                        $warnings.Add("设置看板状态失败（Issue #$number）：$($_.Exception.Message)")
                    }
                }
            }
        }
        Write-Output "看板条目：新增 $added 个"
    }
    catch {
        $warnings.Add("创建 Project 看板失败：$($_.Exception.Message)")
        Write-Output "看板未创建，请手工执行 3 步："
        Write-Output "  1. 仓库 Projects -> New project -> Board"
        Write-Output "  2. 新建 Status 字段，选项：Backlog / Ready / In Progress / Review / Blocked / Done"
        Write-Output "  3. 把本次创建的 Issue 全部 Add to project，再按里程碑从 Backlog 拖到 Ready"
    }
}

if (-not $SkipProject) { New-ProjectBoard }
else { Write-Output "已跳过 Project 看板（-SkipProject）。" }

# ---------------- 可选 PR ----------------

if ($CreatePr) {
    $head = (git rev-parse --abbrev-ref HEAD).Trim()
    if ($head -eq "develop" -or $head -eq "main") {
        $warnings.Add("当前分支是 $head，未创建 PR。")
    }
    else {
        $existingPr = @(Invoke-GitHub -Uri "$api/pulls?state=open&head=${Owner}:$head")
        if ($existingPr.Count -gt 0) {
            Write-Output ("PR 已存在 #{0} {1}" -f $existingPr[0].number, $existingPr[0].html_url)
        }
        else {
            $firstIssue = $issueNumbers.Values | Select-Object -First 1
            $body = @"
## 变更概述

按计划同步标签、里程碑与 Issue，并提交当前分支的设计与接口基线。

Closes #$firstIssue

## 评审重点

- 需求与验收条件是否可验证
- 权限矩阵与状态机是否无歧义
- 契约字段、枚举与数据模型是否一致
- 三域网络与数据库暴露面是否符合课程要求
"@
            $pr = Invoke-GitHub -Method Post -Uri "$api/pulls" -Body @{
                title = "docs: 建立需求、权限、状态机、架构与接口基线"
                head  = $head
                base  = "develop"
                body  = $body
            }
            Write-Output ("PR 已创建 #{0} {1}" -f $pr.number, $pr.html_url)
        }
    }
}

# ---------------- 汇总 ----------------

Write-Output ""
Write-Output "---- 汇总 ----"
Write-Output ("标签 {0} / 里程碑 {1} / Issue {2}（其中 {3} 个已完成并关闭）" -f `
        $plan.labels.Count, $plan.milestones.Count, $plan.issues.Count,
    @($plan.issues | Where-Object state -eq "closed").Count)
if ($warnings.Count -gt 0) {
    Write-Output "警告："
    foreach ($item in $warnings) { Write-Output "  - $item" }
}
Write-Output "完成。下一步：四人各自认领一个 P0 Issue，并在站会同步状态。"
