/**
 * 类型与字典的唯一来源。
 *
 * 结构类型来自 `schema.d.ts`（`npm run generate:api` 从
 * `contracts/openapi/api-gateway.yaml` 生成），这里只做别名与中文标签，
 * 不重复手写后端已有的字段定义（frontend/README.md 规则 8 行以内）。
 */

import type { components } from './schema'

/** 后端保证返回的字段在运行期一定存在，这里把契约里的可选标记收窄成必填。 */
type RequiredFields<T, K extends keyof T> = T & Required<Pick<T, K>>

export type Api = components['schemas']

export type CurrentUser = Api['CurrentUser']
export type RoleCode = Api['RoleCode']
export type OrganizationRef = Api['OrganizationRef']
export type Priority = Api['Priority']
export type Credibility = Api['Credibility']
export type SourceType = Api['ReconRecordWrite']['source_type']
export type RiskLevel = Api['AnalysisReportWrite']['risk_level']
export type ReconStatus = Api['ReconStatus']
export type ReportStatus = Api['ReportStatus']
export type CommandStatus = Api['CommandStatus']
export type AssignmentStatus = Api['AssignmentStatus']
export type AssignmentOutcome = Api['AssignmentOutcome']
export type AISuggestion = Api['AISuggestion']
export type AISuggestionStatus = Api['AISuggestionStatus']
export type AIStage = Api['AIStage']
export type AuditEvent = Api['AuditEvent']
export type AuditTrace = Api['AuditTrace']
export type AuditResult = Api['AuditResult']

export type ReconRecord = RequiredFields<
  Api['ReconRecord'],
  | 'id'
  | 'record_no'
  | 'title'
  | 'source_type'
  | 'content'
  | 'status'
  | 'credibility'
  | 'priority'
  | 'version'
  | 'owner_id'
  | 'created_at'
  | 'updated_at'
  | 'assignments'
  | 'evidence'
>
export type ReconAssignment = Api['ReconAssignment']
export type ReconEvidence = Api['EvidenceItem']
export type AnalysisReport = RequiredFields<
  Api['AnalysisReport'],
  | 'id'
  | 'report_no'
  | 'title'
  | 'status'
  | 'key_findings'
  | 'risk_level'
  | 'recommended_actions'
  | 'priority'
  | 'recon_links'
  | 'version'
  | 'ai_content_confirmed'
  | 'human_confirmed'
  | 'created_at'
  | 'updated_at'
>
export type ReconLink = Api['ReconLink']
export type Command = RequiredFields<
  Api['Command'],
  | 'id'
  | 'command_no'
  | 'title'
  | 'objective'
  | 'content'
  | 'status'
  | 'priority'
  | 'source_report_id'
  | 'assignments'
  | 'version'
  | 'created_at'
  | 'updated_at'
>
export type CommandAssignmentSummary = Api['CommandAssignmentSummary']
export type CommandStatusView = Api['CommandStatusView']
export type Assignment = RequiredFields<
  Api['Assignment'],
  | 'id'
  | 'command_id'
  | 'command_title_snapshot'
  | 'command_content_snapshot'
  | 'priority'
  | 'status'
  | 'version'
  | 'created_at'
  | 'updated_at'
>
export type ExecutionResult = Api['ExecutionResult']
export type Candidate = Api['Candidate']
export type ConflictCheckResult = Api['ConflictCheckResult']
export type EvidenceInput = Api['EvidenceItemInput']

export type ReconRecordWrite = Api['ReconRecordWrite']
export type ReconRecordPatch = Api['ReconRecordPatch']
export type AnalysisReportWrite = Api['AnalysisReportWrite']
export type AnalysisReportPatch = Api['AnalysisReportPatch']
export type CommandWrite = Api['CommandWrite']
export type CommandPatch = Api['CommandPatch']

/** 契约里内联描述的提交体（Gateway pydantic 模型 + docs/workflow.md）。 */
export interface ReconSubmitBody {
  expected_version: number
  analyst_ids: string[]
  priority?: Priority
}

export interface AnalysisSubmitBody {
  expected_version: number
  decision_maker_ids: string[]
  /** 硬要求：AI 内容必须逐条确认/舍弃后才能提交（FR-ANALYSIS-003）。 */
  ai_content_confirmed: boolean
}

export interface CommandIssueBody {
  expected_version: number
  executor_ids: string[]
  conflict_acknowledged: boolean
}

export interface CommandCancelBody {
  expected_version: number
  reason: string
}

export interface TransitionBody {
  expected_version: number
}

export interface RejectAssignmentBody {
  expected_version: number
  reason: string
}

export interface CompleteAssignmentBody {
  expected_version: number
  outcome: AssignmentOutcome
  summary: string
  detail?: string
  evidence?: EvidenceInput[]
}

export interface Page<T> {
  items: T[]
  page: number
  page_size: number
  total: number
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  user: CurrentUser
}

export interface SuggestionRequestBody {
  stage: AIStage
  business_object_type: 'recon_record' | 'analysis_report' | 'command' | 'assignment'
  business_object_id: string
  suggestion_type: string
}

export interface SuggestionDecisionBody {
  decision: 'accepted' | 'edited' | 'rejected'
  edited_content?: Record<string, unknown>
  note?: string
}

// --------------------------------------------------------------------------- 角色与工作台

/** 四个标准业务角色的代码（docs/rbac.md 第 2 节，种子数据里就是这个值）。 */
export const BUSINESS_ROLES = ['reconnaissance', 'analyst', 'decision_maker', 'executor'] as const

/** 管理权限束：不是第五种业务角色，只装 iam:manage / organization:manage / audit:read。 */
export const ADMIN_ROLE = 'administrator'

export type Workspace = 'recon' | 'analysis' | 'decision' | 'execution' | 'audit'

export const roleToWorkspace: Record<string, Workspace> = {
  reconnaissance: 'recon',
  analyst: 'analysis',
  decision_maker: 'decision',
  executor: 'execution',
  [ADMIN_ROLE]: 'audit',
}

export const workspaceToRole: Record<Workspace, string> = {
  recon: 'reconnaissance',
  analysis: 'analyst',
  decision: 'decision_maker',
  execution: 'executor',
  audit: ADMIN_ROLE,
}

export interface WorkspaceMeta {
  name: string
  stage: string
  title: string
  description: string
  action: string
  listLabel: string
  nextStep: string
}

export const workspaceMeta: Record<Workspace, WorkspaceMeta> = {
  recon: {
    name: '侦察员',
    stage: '01 / OBSERVE',
    title: '侦察工作台',
    description: '采集可核实的原始信息：写清来源、可信度与依据，提交时指定分析员。',
    action: '新建侦察记录',
    listLabel: '我的侦察记录',
    nextStep: '先保存草稿，核对来源与证据后再提交；提交后不可直接改写。',
  },
  analysis: {
    name: '分析员',
    stage: '02 / ORIENT',
    title: '分析工作台',
    description: '读取被指派的侦察记录，形成经人工确认的研判，并提交给决策员。',
    action: '编写分析报告',
    listLabel: '我的分析报告',
    nextStep: 'AI 建议只能作为待确认内容，逐条接受/修改/舍弃后才可提交。',
  },
  decision: {
    name: '决策员',
    stage: '03 / DECIDE',
    title: '决策工作台',
    description: '依据被指派的报告下达指令，指定执行员，并对冲突做明确确认。',
    action: '创建行动指令',
    listLabel: '我的行动指令',
    nextStep: '下达前先做冲突检查，二次确认后才真正下达。',
  },
  execution: {
    name: '执行员',
    stage: '04 / ACT',
    title: '执行工作台',
    description: '接收指派给你的指令，记录执行过程并回填结果与证据。',
    action: '填写执行结果',
    listLabel: '我的执行任务',
    nextStep: '先接收指令，再标记开始，最后填写结果；已完成的结果不能重复提交。',
  },
  audit: {
    name: '审计',
    stage: '05 / TRACE',
    title: '审计与调用链',
    description: '按请求 ID 还原一次操作的跨服务调用链，核对每一步的授权与结果。',
    action: '刷新审计日志',
    listLabel: '审计事件',
    nextStep: '用一次提交的 X-Request-ID 查调用链，能把四个服务的事件串起来。',
  },
}

/** 角色 → 可进入的工作台（决策员只进决策台，管理权限束只进审计台）。 */
export function workspacesForRoles(roles: readonly string[]): Workspace[] {
  const result: Workspace[] = []
  for (const role of roles) {
    const workspace = roleToWorkspace[role]
    if (workspace && !result.includes(workspace)) result.push(workspace)
  }
  return result
}

// --------------------------------------------------------------------------- 状态字典

export const priorityNames: Record<string, string> = { normal: '普通', urgent: '紧急' }
export const credibilityNames: Record<string, string> = {
  high: '高',
  medium: '中',
  low: '低',
  unverified: '待核实',
}
export const sourceTypeNames: Record<string, string> = {
  osint: '公开来源',
  sensor: '传感器',
  report: '通报',
  document: '文档',
  other: '其他',
}
export const riskNames: Record<string, string> = { low: '低', medium: '中', high: '高' }
export const outcomeNames: Record<string, string> = {
  success: '成功',
  partial: '部分完成',
  failure: '失败',
}
export const auditResultNames: Record<string, string> = {
  success: '成功',
  failure: '失败',
  denied: '被拒绝',
}
export const aiStatusNames: Record<string, string> = {
  pending: '待人工处理',
  accepted: '已接受',
  edited: '已修改',
  rejected: '已舍弃',
}

export const reconStatusNames: Record<string, string> = {
  draft: '草稿',
  submitting: '提交中',
  assigned: '已指派待分析',
  under_analysis: '分析中',
  analyzed: '已分析',
  rejected: '已退回',
  compensation_required: '提交未完成',
}

export const reportStatusNames: Record<string, string> = {
  draft: '草稿',
  submitting: '提交中',
  assigned: '已提交待研判',
  under_decision: '研判中',
  decided: '已决策',
  rejected: '已退回',
  compensation_required: '提交未完成',
}

export const commandStatusNames: Record<string, string> = {
  draft: '草稿',
  issuing: '下达中',
  issued: '已下达待接收',
  partially_accepted: '部分已接收',
  accepted: '已接收',
  executing: '执行中',
  partially_completed: '部分完成',
  completed: '已完成',
  failed: '已失败',
  rejected: '已拒绝',
  cancelled: '已取消',
  compensation_required: '下达未完成',
}

export const assignmentStatusNames: Record<string, string> = {
  pending: '待接收',
  accepted: '已接收',
  executing: '执行中',
  completed: '已完成',
  failed: '已失败',
  rejected: '已拒绝',
  cancelled: '已取消',
}

export type StatusKind = 'recon' | 'report' | 'command' | 'assignment'

const statusDictionaries: Record<StatusKind, Record<string, string>> = {
  recon: reconStatusNames,
  report: reportStatusNames,
  command: commandStatusNames,
  assignment: assignmentStatusNames,
}

export function statusLabel(kind: StatusKind, status: string): string {
  return statusDictionaries[kind][status] ?? status
}

/** 下拉框统一用这个形状，避免在模板里遍历 Record 造成类型歧义。 */
export interface Option<T extends string = string> {
  value: T
  label: string
}

function toOptions<T extends string>(dictionary: Record<T, string>): Option<T>[] {
  return (Object.keys(dictionary) as T[]).map(value => ({ value, label: dictionary[value] }))
}

export const priorityOptions = toOptions(priorityNames)
export const credibilityOptions = toOptions(credibilityNames)
export const sourceTypeOptions = toOptions(sourceTypeNames)
export const riskOptions = toOptions(riskNames)
export const outcomeOptions = toOptions(outcomeNames)
export const auditResultOptions = toOptions(auditResultNames)
export const reconStatusOptions = toOptions(reconStatusNames)
export const reportStatusOptions = toOptions(reportStatusNames)
export const commandStatusOptions = toOptions(commandStatusNames)
export const assignmentStatusOptions = toOptions(assignmentStatusNames)

/** 状态色调：进行中 / 等待人工 / 成功 / 失败或取消 / 草稿。 */
export type StatusTone = 'draft' | 'active' | 'waiting' | 'done' | 'bad'

const toneByStatus: Record<string, StatusTone> = {
  draft: 'draft',
  pending: 'waiting',
  submitting: 'active',
  issuing: 'active',
  assigned: 'waiting',
  under_analysis: 'active',
  analyzed: 'done',
  under_decision: 'active',
  decided: 'done',
  issued: 'waiting',
  partially_accepted: 'active',
  accepted: 'active',
  executing: 'active',
  partially_completed: 'active',
  completed: 'done',
  failed: 'bad',
  rejected: 'bad',
  cancelled: 'bad',
  compensation_required: 'bad',
}

export function statusTone(status: string): StatusTone {
  return toneByStatus[status] ?? 'waiting'
}

/** 只有这些状态允许编辑草稿（docs/workflow.md 第 2、3、4 节）。 */
export function isEditableDraft(status: string): boolean {
  return status === 'draft'
}
