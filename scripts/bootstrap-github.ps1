param(
    [string]$Owner = "Nev3r1ove9y0rmyX",
    [string]$Repository = "NIS"
)

$ErrorActionPreference = "Stop"

$credentialLines = ("protocol=https`nhost=github.com`n`n" | git credential fill)
$credential = @{}
foreach ($line in $credentialLines) {
    $parts = $line -split "=", 2
    if ($parts.Count -eq 2) {
        $credential[$parts[0]] = $parts[1]
    }
}

if (-not $credential.password) {
    throw "GitHub credential is unavailable from Git Credential Manager."
}

$headers = @{
    Authorization           = "Bearer $($credential.password)"
    Accept                  = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent"            = "NIS-project-bootstrap"
}
$api = "https://api.github.com/repos/$Owner/$Repository"

$labelSpecs = @(
    @{ name = "A"; color = "1D76DB"; description = "成员 A：需求、架构、集成" },
    @{ name = "B"; color = "0E8A16"; description = "成员 B：后端、数据库、审计" },
    @{ name = "C"; color = "FBCA04"; description = "成员 C：前端、交互" },
    @{ name = "D"; color = "D93F0B"; description = "成员 D：网络、部署、测试" },
    @{ name = "P0"; color = "B60205"; description = "基础验收阻塞项" },
    @{ name = "P1"; color = "D93F0B"; description = "重要扩展或质量任务" },
    @{ name = "P2"; color = "FBCA04"; description = "基础验收后处理" },
    @{ name = "frontend"; color = "C5DEF5"; description = "前端" },
    @{ name = "backend"; color = "BFDADC"; description = "后端" },
    @{ name = "network"; color = "5319E7"; description = "网络与部署" },
    @{ name = "docs"; color = "0075CA"; description = "文档" },
    @{ name = "test"; color = "0E8A16"; description = "测试" },
    @{ name = "blocked"; color = "000000"; description = "存在阻塞" }
)

$existingLabels = @(Invoke-RestMethod -Headers $headers -Uri "$api/labels?per_page=100")
foreach ($spec in $labelSpecs) {
    if (-not ($existingLabels | Where-Object name -eq $spec.name)) {
        Invoke-RestMethod -Method Post -Headers $headers -Uri "$api/labels" `
            -Body ($spec | ConvertTo-Json) -ContentType "application/json" | Out-Null
    }
}

$milestoneTitles = @(
    "M0-项目初始化",
    "M1-需求与设计",
    "M2-后端与数据库",
    "M3-前端工作台",
    "M4-网络部署",
    "M5-联调与中期验收",
    "M6-系统加固与对抗演练"
)

$milestones = @(Invoke-RestMethod -Headers $headers -Uri "$api/milestones?state=all&per_page=100")
foreach ($title in $milestoneTitles) {
    if (-not ($milestones | Where-Object title -eq $title)) {
        $body = @{ title = $title; description = "NIS $title 阶段交付" } | ConvertTo-Json
        Invoke-RestMethod -Method Post -Headers $headers -Uri "$api/milestones" `
            -Body $body -ContentType "application/json" | Out-Null
    }
}
$milestones = @(Invoke-RestMethod -Headers $headers -Uri "$api/milestones?state=all&per_page=100")

$issueSpecs = @(
    @{
        title     = "[A][P0] 评审并冻结需求与架构基线"
        labels    = @("A", "P0", "docs")
        milestone = "M1-需求与设计"
        body      = @"
## 目标
组织全员评审并冻结第一版需求、RBAC、状态机、总体架构和验收追踪基线。

## 负责人
主责：A；协作：B、C、D

## 实现范围
- 评审 docs/course-requirements-checklist.md
- 评审 docs/requirements.md、docs/rbac.md、docs/workflow.md
- 评审 docs/architecture.md 和三份 ADR
- 与 B 对齐实体/状态/权限/错误码，与 C 对齐页面动作，与 D 对齐 DMZ 部署
- 记录意见、风险、决策和未决问题

## 验收标准
- [ ] 四名成员均留下评审结论
- [ ] P0 规则无已知矛盾
- [ ] ADR-001 至 ADR-003 被接受或有替代决议
- [ ] B/C/D 能据此开始实现
- [ ] 追踪矩阵与评审结果同步

## 参考
docs/sprint-01.md
"@
    },
    @{
        title     = "[B][P0] 后端骨架、IAM 数据模型与侦察 API"
        labels    = @("B", "P0", "backend", "test")
        milestone = "M2-后端与数据库"
        body      = @"
## 目标
交付可迁移、可测试的后端最小切片：登录、RBAC 基础模型、侦察提交和授权查询。

## 负责人
主责：B；评审：A；联调：C、D

## 实现范围
- FastAPI、SQLAlchemy、Alembic、MySQL、pytest
- User/Role/Permission 多对多和 OrganizationUnit
- 登录、当前用户及角色权限响应
- 侦察记录草稿、提交、分析员授权列表
- ER 图、OpenAPI、种子数据和审计基础

## 验收标准
- [ ] 新环境可迁移数据库并创建四类演示账号
- [ ] 密码不明文保存，合法/非法登录结果正确
- [ ] 侦察员可提交；越权调用被后端拒绝
- [ ] 被指派分析员可查询，其他分析员不可读取
- [ ] 正常、未认证、越权、非法参数测试通过

## 依赖
A 的需求/RBAC/状态机基线评审。
"@
    },
    @{
        title     = "[C][P0] 前端骨架、登录与侦察工作台"
        labels    = @("C", "P0", "frontend", "test")
        milestone = "M3-前端工作台"
        body      = @"
## 目标
交付连接真实 API 的前端最小切片：登录、角色展示、侦察提交和分析员授权列表。

## 负责人
主责：C；评审：A；联调：B

## 实现范围
- Vue 3、Vite、TypeScript、Router、API client
- 登录、当前用户/角色、权限路由
- 侦察列表、新建、草稿、提交
- 分析员被指派记录只读列表
- 加载、空数据及 401/403/422/500 状态

## 验收标准
- [ ] 四类账号角色展示正确，无权限路由被拦截
- [ ] 侦察员通过真实 API 提交，失败时输入不丢失
- [ ] 分析员查询被指派记录
- [ ] 不用静态数据冒充最终联调
- [ ] lint、typecheck、test、build 通过

## 依赖
B 提供经评审的 OpenAPI；临时 mock 必须与契约一致且可切换。
"@
    },
    @{
        title     = "[D][P0] 三域网络最小环境与访问验证"
        labels    = @("D", "P0", "network", "test")
        milestone = "M4-网络部署"
        body      = @"
## 目标
实际建立外网、信任内网、DMZ 三个区域，并用测试证据证明允许和拒绝路径。

## 负责人
主责：D；评审：A；协作：B、C

## 实现范围
- 盘点四台电脑、网卡、内存、虚拟化软件和交换设备
- 固化 IP、网关、接口和节点表
- 创建 iKuai/等价软路由及三网段
- 在 DMZ 预留 Web/API 与中心数据库节点
- 数据库不映射外网，DMZ 到内网全部拒绝
- 保存配置步骤、日志和脱敏证据

## 验收标准
- [ ] 三个区域使用不同网段
- [ ] 内网访问外网和 DMZ 测试服务成功
- [ ] 外网访问映射后的 DMZ 服务成功
- [ ] DMZ 访问内网测试服务失败且有防火墙日志
- [ ] 另一名成员可依据文档复查配置

## 依赖
docs/architecture.md、ADR-002 和 docs/network-lab-plan.md。
"@
    }
)

$allIssues = @(Invoke-RestMethod -Headers $headers -Uri "$api/issues?state=all&per_page=100")
$createdIssues = @()
foreach ($spec in $issueSpecs) {
    $existing = $allIssues | Where-Object { $_.title -eq $spec.title -and -not $_.pull_request } | Select-Object -First 1
    if ($existing) {
        $createdIssues += $existing
        continue
    }

    $milestone = $milestones | Where-Object title -eq $spec.milestone | Select-Object -First 1
    $payload = @{
        title     = $spec.title
        body      = $spec.body
        labels    = $spec.labels
        milestone = $milestone.number
    } | ConvertTo-Json -Depth 5

    $createdIssues += Invoke-RestMethod -Method Post -Headers $headers -Uri "$api/issues" `
        -Body $payload -ContentType "application/json"
}

$aIssue = $createdIssues | Where-Object title -like "[[]A[]]*" | Select-Object -First 1
$pulls = @(Invoke-RestMethod -Headers $headers -Uri "$api/pulls?state=open&head=${Owner}:docs/a-requirements-architecture")
if ($pulls.Count -eq 0) {
    $prBody = @"
## 变更概述

建立课程要求核对、需求规格、RBAC、业务状态机、总体架构、ADR、追踪矩阵和 Sprint 01 任务基线。

Closes #$($aIssue.number)

## 评审重点

- 用户/角色/权限多对多是否明确
- 四环节 AI 人在回路是否可实现
- 多用户冲突规则是否合理
- API 与数据库位于 DMZ 服务侧是否符合现场条件
- P0/P1/P2 范围是否接受
"@
    $prPayload = @{
        title = "docs: 建立需求、权限、状态机与架构基线"
        head  = "docs/a-requirements-architecture"
        base  = "develop"
        body  = $prBody
    } | ConvertTo-Json

    $pr = Invoke-RestMethod -Method Post -Headers $headers -Uri "$api/pulls" `
        -Body $prPayload -ContentType "application/json"
    $prLabels = @{ labels = @("A", "P0", "docs") } | ConvertTo-Json
    Invoke-RestMethod -Method Post -Headers $headers -Uri "$api/issues/$($pr.number)/labels" `
        -Body $prLabels -ContentType "application/json" | Out-Null
}
else {
    $pr = $pulls[0]
}

$createdIssues | ForEach-Object { Write-Output "ISSUE #$($_.number) $($_.html_url)" }
Write-Output "PR #$($pr.number) $($pr.html_url)"

$credential.Clear()
$credentialLines = $null
