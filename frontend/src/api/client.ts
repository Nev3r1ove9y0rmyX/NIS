/**
 * HTTP 客户端：统一注入身份、角色上下文、请求 ID 与幂等键，并把后端错误体
 * 归一化成前端可用的结构。
 *
 * 后端错误体契约（contracts/schemas/common.yaml `Error`）：
 *   { code, message, request_id, details }
 * 校验错误在 `details.issues[]` 里给出 `{ field, reason, type }`；前端按字段回显，
 * 不再把整段后端文本塞进提示框。
 */

const DEFAULT_TIMEOUT_MS = 15000

/** 与 Vite dev server 的 /api/v1 代理、nginx 的同源反向代理保持一致。 */
export const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/+$/, '')

export interface FieldIssue {
  field: string
  message: string
}

interface TransportConfig {
  token: () => string | null
  roleContext: () => string | null
  onUnauthorized: () => void
}

let transport: TransportConfig = {
  token: () => null,
  roleContext: () => null,
  onUnauthorized: () => {},
}

export function configureTransport(config: Partial<TransportConfig>): void {
  transport = { ...transport, ...config }
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId = '',
    readonly issues: FieldIssue[] = [],
    readonly details: Record<string, unknown> = {},
  ) {
    super(message)
    this.name = 'ApiError'
  }

  get unauthorized(): boolean {
    return this.status === 401
  }

  get forbidden(): boolean {
    return this.status === 403
  }

  get notFound(): boolean {
    return this.status === 404
  }

  get conflict(): boolean {
    return this.status === 409
  }

  /** 版本冲突：别人先改了同一条记录，需要刷新后再决定。 */
  get versionConflict(): boolean {
    return this.code === 'VERSION_CONFLICT'
  }

  /** 状态冲突：当前状态不允许这个动作（例如已提交还想改草稿）。 */
  get workflowConflict(): boolean {
    return this.code === 'WORKFLOW_CONFLICT'
  }

  get validation(): boolean {
    return this.status === 422
  }

  /** 网络中断或跨域失败，前端据此显示「检查网络后重试」。 */
  get offline(): boolean {
    return this.status === 0
  }

  get retryable(): boolean {
    return this.status === 0 || this.status >= 500
  }

  /** 按字段名取错误，表单直接用它做 aria-describedby。 */
  issueFor(field: string): string {
    return this.issues.find(item => item.field === field)?.message ?? ''
  }
}

const STATUS_FALLBACK: Record<number, { code: string; message: string }> = {
  400: { code: 'INVALID_REQUEST', message: '请求未被接受，请检查填写内容。' },
  401: { code: 'UNAUTHENTICATED', message: '登录已失效，请重新登录。' },
  403: { code: 'FORBIDDEN', message: '你没有执行此操作的权限。' },
  404: { code: 'RESOURCE_NOT_FOUND', message: '记录不存在或你无权查看。' },
  409: { code: 'WORKFLOW_CONFLICT', message: '记录状态已变化，请刷新后重新确认。' },
  422: { code: 'VALIDATION_ERROR', message: '填写内容未通过校验，请检查标注字段。' },
  423: { code: 'ACCOUNT_LOCKED', message: '账号已被临时锁定，请联系管理员。' },
  502: { code: 'UPSTREAM_ERROR', message: '下游服务暂时不可用，请稍后重试。' },
  503: { code: 'SERVICE_UNAVAILABLE', message: '服务暂时不可用，请稍后重试。' },
  504: { code: 'UPSTREAM_TIMEOUT', message: '服务响应超时，请稍后重试。' },
}

const CONFLICT_MESSAGES: Record<string, string> = {
  VERSION_CONFLICT: '这条记录已被其他成员更新。请刷新后核对差异，再重新提交。',
  WORKFLOW_CONFLICT: '当前状态不允许这个操作。请刷新页面确认最新状态。',
}

const ERROR_CODE_MESSAGES: Record<string, string> = {
  INVALID_REQUEST: '请求参数不被接受，请检查填写内容。',
  VALIDATION_ERROR: '填写内容未通过校验，请检查标注字段。',
  FORBIDDEN: '你没有执行此操作的权限。',
  RESOURCE_NOT_FOUND: '记录不存在或你无权查看。',
  UNAUTHENTICATED: '登录已失效，请重新登录。',
  SERVICE_UNAVAILABLE: '服务暂时不可用，请稍后重试。',
}

/** 后端返回的 message 是面向用户的中文提示，但绝不把 HTML/堆栈塞进界面。 */
function safeServerMessage(value: unknown): string {
  if (typeof value !== 'string') return ''
  const text = value.trim()
  if (!text || text.length > 200) return ''
  if (/[<>]/.test(text) || /traceback|exception|stack/i.test(text)) return ''
  return text
}

function parseIssues(details: Record<string, unknown>): FieldIssue[] {
  const raw = details.issues
  if (!Array.isArray(raw)) return []
  const issues: FieldIssue[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const record = item as Record<string, unknown>
    const field = typeof record.field === 'string' ? record.field : ''
    const reason = typeof record.reason === 'string' ? record.reason : ''
    if (!field) continue
    issues.push({ field, message: safeServerMessage(reason) || '此字段格式或取值不正确。' })
  }
  return issues
}

export function parseError(status: number, body: unknown): ApiError {
  const fallback = STATUS_FALLBACK[status] ?? {
    code: status >= 500 ? 'INTERNAL_ERROR' : 'INVALID_REQUEST',
    message: status >= 500 ? '服务暂时不可用，请稍后重试。' : '请求失败，请稍后重试。',
  }
  const payload = (body && typeof body === 'object' ? body : {}) as Record<string, unknown>
  const code = typeof payload.code === 'string' && payload.code ? payload.code : fallback.code
  const requestId = typeof payload.request_id === 'string' ? payload.request_id : ''
  const details = (payload.details && typeof payload.details === 'object'
    ? payload.details
    : {}) as Record<string, unknown>
  const message =
    (status === 409 && CONFLICT_MESSAGES[code]) ||
    safeServerMessage(payload.message) ||
    ERROR_CODE_MESSAGES[code] ||
    fallback.message
  return new ApiError(status, code, message, requestId, parseIssues(details), details)
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
  /** 关键提交必须复用同一把键，网络重试才不会生成重复记录。 */
  idempotencyKey?: string
  signal?: AbortSignal
  timeoutMs?: number
}

function requestId(): string {
  try {
    return crypto.randomUUID()
  } catch {
    return `req-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`
  }
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {  if (!path.startsWith('/') || path.startsWith('//')) {
    throw new ApiError(0, 'INVALID_PATH', '接口路径配置不正确。')
  }

  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? DEFAULT_TIMEOUT_MS)
  const forwardAbort = () => controller.abort()
  options.signal?.addEventListener('abort', forwardAbort)

  const headers = new Headers({ Accept: 'application/json', 'X-Request-ID': requestId() })
  const token = transport.token()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const roleContext = transport.roleContext()
  if (roleContext) headers.set('X-Role-Context', roleContext)
  if (options.idempotencyKey) headers.set('Idempotency-Key', options.idempotencyKey)

  let payload: BodyInit | undefined
  if (options.body !== undefined) {
    headers.set('Content-Type', 'application/json')
    payload = JSON.stringify(options.body)
  }

  try {
    const response = await fetch(`${apiBaseUrl}${path}`, {
      method: options.method ?? 'GET',
      headers,
      body: payload,
      signal: controller.signal,
      cache: 'no-store',
      credentials: 'omit',
      redirect: 'error',
    })

    // 必须把响应体读完：204/空体的响应若直接丢弃，Chromium 会把这条请求记为
    // net::ERR_ABORTED（DevTools 里像"请求失败"），而服务端其实已经成功。
    const text = await response.text().catch(() => '')
    let body: unknown = null
    if (text) {
      try {
        body = JSON.parse(text)
      } catch {
        body = null
      }
    }

    if (!response.ok) {
      if (response.status === 401) transport.onUnauthorized()
      throw parseError(response.status, body)
    }
    return (text ? body : undefined) as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    const aborted = controller.signal.aborted
    const timedOut = aborted && !options.signal?.aborted
    throw new ApiError(
      0,
      timedOut ? 'TIMEOUT' : 'NETWORK_ERROR',
      timedOut
        ? '请求超时，请检查网络后重试。'
        : '无法连接服务，请确认 Gateway 已启动后重试。',
    )
  } finally {
    clearTimeout(timeout)
    options.signal?.removeEventListener('abort', forwardAbort)
  }
}

/**
 * 下载受控证据文件：证据目录不对外公开，必须带身份走业务接口，
 * 因此不能用 `<a href>` 直链，只能带 Authorization 取回 Blob。
 */
export async function requestBlob(path: string, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<Blob> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), timeoutMs)
  const headers = new Headers({ Accept: '*/*', 'X-Request-ID': requestId() })
  const token = transport.token()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const roleContext = transport.roleContext()
  if (roleContext) headers.set('X-Role-Context', roleContext)

  try {
    const response = await fetch(`${apiBaseUrl}${path}`, {
      headers,
      signal: controller.signal,
      cache: 'no-store',
      credentials: 'omit',
      redirect: 'error',
    })
    if (!response.ok) {
      const body: unknown = await response.json().catch(() => null)
      if (response.status === 401) transport.onUnauthorized()
      throw parseError(response.status, body)
    }
    return await response.blob()
  } catch (error) {
    if (error instanceof ApiError) throw error
    throw new ApiError(0, 'NETWORK_ERROR', '证据下载失败，请检查网络后重试。')
  } finally {
    clearTimeout(timeout)
  }
}

