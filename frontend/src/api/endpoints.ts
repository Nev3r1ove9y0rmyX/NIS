/**
 * 接口封装：一个函数对应契约里的一个 operationId。
 *
 * 路径与字段全部来自 `contracts/openapi/api-gateway.yaml`；如果某天两者不一致，
 * 先改契约再改这里（docs/api-catalog.md 第 7 节）。前端不发明字段。
 */

import { request, requestBlob } from './client'
import type {
  AISuggestion,
  AnalysisReport,
  AnalysisReportPatch,
  AnalysisReportWrite,
  AnalysisSubmitBody,
  Assignment,
  AuditEvent,
  AuditTrace,
  Candidate,
  Command,
  CommandCancelBody,
  CommandIssueBody,
  CommandPatch,
  CommandStatusView,
  CommandWrite,
  CompleteAssignmentBody,
  CurrentUser,
  EvidenceInput,
  LoginResponse,
  Page,
  ReconRecord,
  ReconRecordPatch,
  ReconRecordWrite,
  ReconSubmitBody,
  RejectAssignmentBody,
  SuggestionDecisionBody,
  SuggestionRequestBody,
  TransitionBody,
} from './types'

function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export interface PageQuery {
  page?: number
  page_size?: number
}

// --------------------------------------------------------------------------- 认证与身份

export const authApi = {
  login: (username: string, password: string) =>
    request<LoginResponse>('/auth/login', { method: 'POST', body: { username, password } }),

  me: () => request<CurrentUser>('/auth/me'),

  logout: () => request<void>('/auth/logout', { method: 'POST' }),
}

// --------------------------------------------------------------------------- 候选接收人

export const candidateApi = {
  list: (targetRole: string, pageSize = 100) =>
    request<Page<Candidate>>(`/candidates${query({ target_role: targetRole, page_size: pageSize })}`),
}

// --------------------------------------------------------------------------- 侦察记录

export interface ReconListQuery extends PageQuery {
  status?: string
  priority?: string
}

export const reconApi = {
  list: (params: ReconListQuery = {}) =>
    request<Page<ReconRecord>>(`/recon-records${query({ ...params })}`),

  get: (id: string) => request<ReconRecord>(`/recon-records/${id}`),

  create: (body: ReconRecordWrite, idempotencyKey: string) =>
    request<ReconRecord>('/recon-records', {
      method: 'POST',
      body,
      idempotencyKey,
    }),

  patch: (id: string, body: ReconRecordPatch) =>
    request<ReconRecord>(`/recon-records/${id}`, { method: 'PATCH', body }),

  submit: (id: string, body: ReconSubmitBody, idempotencyKey: string) =>
    request<ReconRecord>(`/recon-records/${id}/submit`, {
      method: 'POST',
      body,
      idempotencyKey,
    }),

  evidencePath: (recordId: string, evidenceId: string) =>
    `/recon-records/${recordId}/evidence/${evidenceId}`,

  downloadEvidence: (recordId: string, evidenceId: string) =>
    requestBlob(`/recon-records/${recordId}/evidence/${evidenceId}`),
}

// --------------------------------------------------------------------------- 分析报告

export interface ReportListQuery extends PageQuery {
  status?: string
  recon_record_id?: string
}

export const reportApi = {
  list: (params: ReportListQuery = {}) =>
    request<Page<AnalysisReport>>(`/analysis-reports${query({ ...params })}`),

  get: (id: string) => request<AnalysisReport>(`/analysis-reports/${id}`),

  create: (body: AnalysisReportWrite, idempotencyKey: string) =>
    request<AnalysisReport>('/analysis-reports', {
      method: 'POST',
      body,
      idempotencyKey,
    }),

  patch: (id: string, body: AnalysisReportPatch) =>
    request<AnalysisReport>(`/analysis-reports/${id}`, { method: 'PATCH', body }),

  submit: (id: string, body: AnalysisSubmitBody, idempotencyKey: string) =>
    request<AnalysisReport>(`/analysis-reports/${id}/submit`, {
      method: 'POST',
      body,
      idempotencyKey,
    }),
}

// --------------------------------------------------------------------------- 决策指令

export interface CommandListQuery extends PageQuery {
  status?: string
  priority?: string
}

export const commandApi = {
  list: (params: CommandListQuery = {}) =>
    request<Page<Command>>(`/commands${query({ ...params })}`),

  get: (id: string) => request<Command>(`/commands/${id}`),

  create: (body: CommandWrite, idempotencyKey: string) =>
    request<Command>('/commands', { method: 'POST', body, idempotencyKey }),

  patch: (id: string, body: CommandPatch) =>
    request<Command>(`/commands/${id}`, { method: 'PATCH', body }),

  issue: (id: string, body: CommandIssueBody, idempotencyKey: string) =>
    request<Command>(`/commands/${id}/issue`, { method: 'POST', body, idempotencyKey }),

  cancel: (id: string, body: CommandCancelBody) =>
    request<Command>(`/commands/${id}/cancel`, { method: 'POST', body }),

  status: (id: string) => request<CommandStatusView>(`/commands/${id}/status`),

  results: (id: string) =>
    request<{ items: CommandResultItem[] }>(`/commands/${id}/results`),

  conflicts: (sourceReportId: string, objective?: string, excludeCommandId?: string) =>
    request<import('./types').ConflictCheckResult>(
      `/commands/conflicts${query({
        source_report_id: sourceReportId,
        objective,
        exclude_command_id: excludeCommandId,
      })}`,
    ),
}

/** `GET /commands/{id}/results` 的条目（Gateway 取 execution 的 summary）。 */
export interface CommandResultItem {
  assignment_id: string
  executor_id: string
  status: string
  outcome?: string
  completed_at?: string
}

// --------------------------------------------------------------------------- 执行分配

export interface AssignmentListQuery extends PageQuery {
  status?: string
}

export const assignmentApi = {
  list: (params: AssignmentListQuery = {}) =>
    request<Page<Assignment>>(`/assignments${query({ ...params })}`),

  get: (id: string) => request<Assignment>(`/assignments/${id}`),

  accept: (id: string, body: TransitionBody) =>
    request<Assignment>(`/assignments/${id}/accept`, { method: 'POST', body }),

  reject: (id: string, body: RejectAssignmentBody) =>
    request<Assignment>(`/assignments/${id}/reject`, { method: 'POST', body }),

  start: (id: string, body: TransitionBody) =>
    request<Assignment>(`/assignments/${id}/start`, { method: 'POST', body }),

  complete: (id: string, body: CompleteAssignmentBody, idempotencyKey: string) =>
    request<Assignment>(`/assignments/${id}/complete`, {
      method: 'POST',
      body,
      idempotencyKey,
    }),

  downloadEvidence: (assignmentId: string, evidenceId: string) =>
    requestBlob(`/assignments/${assignmentId}/evidence/${evidenceId}`),
}

// --------------------------------------------------------------------------- AI 建议

export const aiApi = {
  create: (body: SuggestionRequestBody) =>
    request<AISuggestion>('/ai/suggestions', { method: 'POST', body }),

  get: (id: string) => request<AISuggestion>(`/ai/suggestions/${id}`),

  decide: (id: string, body: SuggestionDecisionBody) =>
    request<AISuggestion>(`/ai/suggestions/${id}/decision`, { method: 'POST', body }),
}

// --------------------------------------------------------------------------- 审计

export interface AuditListQuery extends PageQuery {
  resource_type?: string
  resource_id?: string
  request_id?: string
  actor_user_id?: string
  result?: string
  from?: string
  to?: string
}

export const auditApi = {
  list: (params: AuditListQuery = {}) => request<Page<AuditEvent>>(`/audit-events${query({ ...params })}`),

  trace: (requestId: string) => request<AuditTrace>(`/audit-events/traces/${requestId}`),
}

/** 把下载到的 Blob 存成本地文件，避免证据内容只停留在内存里。 */
export function saveBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export type { EvidenceInput }
