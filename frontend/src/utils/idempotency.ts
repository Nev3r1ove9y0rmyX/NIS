/** 幂等键：关键提交必须复用同一把键（frontend/README.md 规则 2）。 */
export function newIdempotencyKey(): string {
  try {
    return crypto.randomUUID()
  } catch {
    return `key-${Date.now()}-${Math.random().toString(16).slice(2, 12)}`
  }
}

/** 每次请求的追踪 ID：与审计日志的 X-Request-ID 对齐，便于报障时定位。 */
export function newRequestId(): string {
  try {
    return crypto.randomUUID()
  } catch {
    return `req-${Date.now()}`
  }
}
