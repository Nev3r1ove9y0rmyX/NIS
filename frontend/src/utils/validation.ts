/**
 * 表单校验：字段名与长度上限和 Gateway 的 pydantic 模型保持一致
 * （services/api-gateway/app/routes_records.py、routes_tasks.py）。
 *
 * 前端校验只为「早点告诉用户哪里不对」，后端仍是最终裁判。
 */

import type { EvidenceInput } from '../api/types'

export type FieldErrors = Record<string, string>

export interface ReconDraft {
  title: string
  source_type: string
  source_ref: string
  content: string
  credibility: string
  priority: string
}

export interface ReportDraft {
  title: string
  recon_record_ids: string[]
  key_findings: string
  relations: string
  risk_level: string
  recommended_actions: string
  priority: string
}

export interface CommandDraft {
  title: string
  objective: string
  content: string
  priority: string
  deadline: string
  source_report_id: string
}

export interface ResultDraft {
  outcome: string
  summary: string
  detail: string
}

const SOURCE_TYPES = ['osint', 'sensor', 'report', 'document', 'other']
const CREDIBILITY = ['high', 'medium', 'low', 'unverified']
const RISK = ['low', 'medium', 'high']
const PRIORITY = ['normal', 'urgent']
const OUTCOME = ['success', 'partial', 'failure']

function lengthBetween(value: string, min: number, max: number): boolean {
  const length = value.trim().length
  return length >= min && length <= max
}

export function validateRecon(draft: ReconDraft): FieldErrors {
  const errors: FieldErrors = {}
  if (!lengthBetween(draft.title, 2, 200)) errors.title = '标题需要 2–200 个字符。'
  if (!SOURCE_TYPES.includes(draft.source_type)) errors.source_type = '请选择信息来源类型。'
  if (draft.source_ref.trim().length > 500) errors.source_ref = '来源说明不能超过 500 个字符。'
  if (!lengthBetween(draft.content, 10, 8000)) errors.content = '正文需要 10–8000 个字符。'
  if (!CREDIBILITY.includes(draft.credibility)) errors.credibility = '请选择可信度。'
  if (!PRIORITY.includes(draft.priority)) errors.priority = '请选择优先级。'
  return errors
}

export function validateReport(draft: ReportDraft): FieldErrors {
  const errors: FieldErrors = {}
  if (!lengthBetween(draft.title, 2, 200)) errors.title = '标题需要 2–200 个字符。'
  if (!draft.recon_record_ids.length) errors.recon_record_ids = '至少要关联一条侦察记录。'
  if (!lengthBetween(draft.key_findings, 10, 8000)) errors.key_findings = '关键发现需要 10–8000 个字符。'
  if (draft.relations.trim().length > 8000) errors.relations = '关联关系不能超过 8000 个字符。'
  if (!RISK.includes(draft.risk_level)) errors.risk_level = '请选择风险等级。'
  if (!lengthBetween(draft.recommended_actions, 2, 4000)) {
    errors.recommended_actions = '建议手段需要 2–4000 个字符。'
  }
  if (!PRIORITY.includes(draft.priority)) errors.priority = '请选择优先级。'
  return errors
}

export function validateCommand(draft: CommandDraft): FieldErrors {
  const errors: FieldErrors = {}
  if (!lengthBetween(draft.title, 2, 200)) errors.title = '标题需要 2–200 个字符。'
  if (!lengthBetween(draft.objective, 2, 500)) errors.objective = '目标需要 2–500 个字符。'
  if (!lengthBetween(draft.content, 10, 8000)) errors.content = '行动内容需要 10–8000 个字符。'
  if (!PRIORITY.includes(draft.priority)) errors.priority = '请选择优先级。'
  if (!draft.source_report_id) errors.source_report_id = '指令必须关联一份已被指派的报告。'
  if (draft.deadline) {
    const time = Date.parse(draft.deadline)
    if (Number.isNaN(time)) errors.deadline = '截止时间格式不正确。'
    else if (time <= Date.now()) errors.deadline = '截止时间需要晚于当前时间。'
  }
  return errors
}

export function validateResult(draft: ResultDraft): FieldErrors {
  const errors: FieldErrors = {}
  if (!OUTCOME.includes(draft.outcome)) errors.outcome = '请选择执行结论。'
  if (!lengthBetween(draft.summary, 1, 2000)) errors.summary = '结果摘要需要 1–2000 个字符。'
  if (draft.detail.trim().length > 8000) errors.detail = '详情不能超过 8000 个字符。'
  return errors
}

export interface EvidenceDraft extends EvidenceInput {
  localFile?: File
}

const MAX_EVIDENCE_BYTES = 10 * 1024 * 1024
const MAX_EVIDENCE_COUNT = 5
const MEDIA_TYPES: Record<string, string[]> = {
  'image/png': ['png'],
  'image/jpeg': ['jpg', 'jpeg'],
  'application/pdf': ['pdf'],
  'text/plain': ['txt'],
}

/**
 * 证据文件校验。
 *
 * 说明：当前契约只有「证据元数据 + 受控目录下载」，没有上传端点
 * （docs/frontend-integration.md 第 4 节记录了该缺口）。前端因此只做两件事：
 * 校验文件类型/大小，并在浏览器内算出 sha256 作为元数据一起提交。
 */
export function validateEvidenceFile(file: File): string | null {
  if (file.size > MAX_EVIDENCE_BYTES) return '单个证据文件不能超过 10 MB。'
  if (file.size === 0) return '空文件不能作为证据。'
  const extension = file.name.split('.').at(-1)?.toLowerCase() ?? ''
  const allowed = MEDIA_TYPES[file.type]
  if (!allowed || !allowed.includes(extension)) {
    return '仅支持 PNG、JPEG、PDF、TXT，且扩展名要与文件类型一致。'
  }
  return null
}

export function evidenceLimitError(count: number): string | null {
  return count >= MAX_EVIDENCE_COUNT ? `最多关联 ${MAX_EVIDENCE_COUNT} 份证据。` : null
}

export function hasErrors(errors: FieldErrors): boolean {
  return Object.keys(errors).length > 0
}
