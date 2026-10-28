import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, configureTransport, parseError, request } from '../api/client'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
  configureTransport({ token: () => null, roleContext: () => null, onUnauthorized: () => {} })
})

describe('错误体归一化', () => {
  it('把 details.issues 映射成字段错误', () => {
    const error = parseError(422, {
      code: 'VALIDATION_ERROR',
      message: '字段校验错误',
      request_id: 'req-1',
      details: { issues: [{ field: 'title', reason: '长度不足', type: 'too_short' }] },
    })
    expect(error.validation).toBe(true)
    expect(error.issues).toEqual([{ field: 'title', message: '长度不足' }])
    expect(error.issueFor('title')).toBe('长度不足')
    expect(error.issueFor('content')).toBe('')
    expect(error.requestId).toBe('req-1')
  })

  it('区分 VERSION_CONFLICT 与 WORKFLOW_CONFLICT', () => {
    const version = parseError(409, { code: 'VERSION_CONFLICT', message: '版本不匹配', request_id: 'r' })
    const workflow = parseError(409, { code: 'WORKFLOW_CONFLICT', message: '当前状态不允许', request_id: 'r' })
    expect(version.conflict).toBe(true)
    expect(version.versionConflict).toBe(true)
    expect(version.message).toContain('刷新')
    expect(workflow.versionConflict).toBe(false)
    expect(workflow.workflowConflict).toBe(true)
  })

  it('使用后端给用户看的中文提示', () => {
    const error = parseError(403, { code: 'FORBIDDEN', message: '没有执行该操作的权限', request_id: 'r' })
    expect(error.forbidden).toBe(true)
    expect(error.message).toBe('没有执行该操作的权限')
  })

  it('不把 HTML 或堆栈回显到界面', () => {
    const error = parseError(500, {
      code: 'INTERNAL_ERROR',
      message: '<html>Traceback (most recent call last)</html>',
      request_id: 'r',
    })
    expect(error.message).not.toContain('<')
    expect(error.message).not.toContain('Traceback')
    expect(error.retryable).toBe(true)
  })

  it('未知状态码给通用提示而不是空白', () => {
    const error = parseError(418, null)
    expect(error.message.length).toBeGreaterThan(0)
    expect(error.code).toBe('INVALID_REQUEST')
  })
})

describe('请求封装', () => {
  beforeEach(() => {
    configureTransport({
      token: () => 'token-123',
      roleContext: () => 'analyst',
      onUnauthorized: () => {},
    })
  })

  it('注入身份、角色上下文、请求 ID 与幂等键', async () => {
    const fetchMock = vi.fn(async () => jsonResponse(200, { ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await request('/recon-records', { method: 'POST', body: { title: 'x' }, idempotencyKey: 'key-1' })

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    const headers = init.headers as Headers
    expect(headers.get('Authorization')).toBe('Bearer token-123')
    expect(headers.get('X-Role-Context')).toBe('analyst')
    expect(headers.get('Idempotency-Key')).toBe('key-1')
    expect(headers.get('Content-Type')).toBe('application/json')
    expect(headers.get('X-Request-ID')).toMatch(/[0-9a-f-]{8,}/)
  })

  it('204 返回 undefined，不尝试解析 JSON', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 204 })))
    await expect(request('/auth/logout', { method: 'POST' })).resolves.toBeUndefined()
  })

  it('401 触发会话失效回调并抛出可识别错误', async () => {
    const onUnauthorized = vi.fn()
    configureTransport({ token: () => 'token-123', onUnauthorized })
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(401, { code: 'UNAUTHENTICATED', message: '登录已失效', request_id: 'r' })),
    )

    await expect(request('/auth/me')).rejects.toBeInstanceOf(ApiError)
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
  })

  it('网络异常归一化成离线错误，可重试', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    const error = (await request('/recon-records').catch(cause => cause)) as ApiError
    expect(error.offline).toBe(true)
    expect(error.retryable).toBe(true)
    expect(error.message).toContain('无法连接')
  })

  it('拒绝非站内相对路径', async () => {
    const error = (await request('https://evil.example/x').catch(cause => cause)) as ApiError
    expect(error.code).toBe('INVALID_PATH')
  })
})
