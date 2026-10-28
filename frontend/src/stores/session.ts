/**
 * 会话状态：一次登录拿到全部角色与权限，工作台在所属角色间切换
 * （docs/rbac.md 第 5 节）。多角色用户必须带 `X-Role-Context`，单角色可省略。
 *
 * 前端权限只用于隐藏入口与导航，真正的授权判断始终在服务端。
 */

import { reactive } from 'vue'
import { ApiError, configureTransport } from '../api/client'
import { authApi } from '../api/endpoints'
import {
  BUSINESS_ROLES,
  workspaceToRole,
  workspacesForRoles,
  type CurrentUser,
  type Workspace,
} from '../api/types'

const TOKEN_KEY = 'nis.access-token'
const WORKSPACE_KEY = 'nis.workspace'

function readStorage(key: string): string | null {
  try {
    return sessionStorage.getItem(key)
  } catch {
    return null
  }
}

function writeStorage(key: string, value: string | null): void {
  try {
    if (value === null) sessionStorage.removeItem(key)
    else sessionStorage.setItem(key, value)
  } catch {
    /* 隐私模式下退化为内存会话，不影响本次操作。 */
  }
}

export const session = reactive({
  token: readStorage(TOKEN_KEY),
  user: null as CurrentUser | null,
  /** 当前工作台，决定 `X-Role-Context` 与默认筛选。 */
  workspace: readStorage(WORKSPACE_KEY) as Workspace | null,
  ready: false,
  restoring: false,
  loginPending: false,
  loginError: '',
})

let restoring: Promise<void> | null = null
let generation = 0

/** 用户能进入的工作台；顺序决定登录后的默认落点。 */
export function allowedWorkspaces(): Workspace[] {
  const roles = session.user?.roles ?? []
  return workspacesForRoles(roles)
}

export function isMultiRole(): boolean {
  return (session.user?.roles.length ?? 0) > 1
}

/**
 * 角色上下文：多角色用户必须显式声明本次操作用哪个角色；
 * 单角色用户省略（后端按唯一角色推断）。
 */
export function roleContext(): string | null {
  if (!session.user || !session.workspace) return null
  if (!isMultiRole()) return null
  const role = workspaceToRole[session.workspace]
  return (session.user.roles as string[]).includes(role) ? role : null
}

export function can(permission: string): boolean {
  return session.user?.permissions.includes(permission) ?? false
}

/** 当前身份能做什么（用于按钮可见性，不作为安全边界）。 */
export function hasAnyRole(...roles: string[]): boolean {
  return roles.some(role => (session.user?.roles as string[] | undefined)?.includes(role) ?? false)
}

export function homePath(): string {
  const workspaces = allowedWorkspaces()
  return workspaces.length ? `/w/${workspaces[0]}` : '/no-role'
}

export function workspacePath(workspace: Workspace): string {
  return `/w/${workspace}`
}

export function clearSession(): void {
  generation += 1
  session.token = null
  session.user = null
  session.workspace = null
  session.ready = true
  writeStorage(TOKEN_KEY, null)
  writeStorage(WORKSPACE_KEY, null)
  window.dispatchEvent(new Event('nis:session-cleared'))
}

/** 401：清理本地状态并让路由跳到登录页（保留来源路径）。 */
function handleUnauthorized(): void {
  if (!session.token) return
  clearSession()
  window.dispatchEvent(new Event('nis:unauthorized'))
}

configureTransport({
  token: () => session.token,
  roleContext,
  onUnauthorized: handleUnauthorized,
})

/**
 * 校验后端返回的用户结构。
 *
 * 只依赖契约字段：id / username / display_name / roles / permissions。
 * 角色代码必须在四个标准业务角色或管理权限束之内，否则拒绝进入，
 * 避免"未知角色"绕过守卫。
 */
export function parseUser(value: unknown): CurrentUser {
  if (!value || typeof value !== 'object') throw new ApiError(0, 'BAD_USER', '身份接口返回结构与契约不一致。')
  const user = value as Record<string, unknown>
  const roles = Array.isArray(user.roles) ? user.roles.filter((item): item is string => typeof item === 'string') : []
  const permissions = Array.isArray(user.permissions)
    ? user.permissions.filter((item): item is string => typeof item === 'string')
    : []
  if (!user.id || typeof user.username !== 'string') {
    throw new ApiError(0, 'BAD_USER', '身份接口返回结构与契约不一致。')
  }
  if (!roles.length) {
    throw new ApiError(403, 'NO_ROLE', '当前账号没有可用的角色，请联系管理员分配。')
  }
  if (!roles.some(role => role === 'administrator' || BUSINESS_ROLES.includes(role as (typeof BUSINESS_ROLES)[number]))) {
    throw new ApiError(403, 'NO_ROLE', '当前账号没有可用的角色，请联系管理员分配。')
  }
  return {
    id: String(user.id),
    username: user.username,
    display_name: typeof user.display_name === 'string' ? user.display_name : user.username,
    organization: (user.organization ?? { id: '', code: '', name: '' }) as CurrentUser['organization'],
    roles: roles as CurrentUser['roles'],
    permissions,
  }
}

/** 会话恢复：带 Token 时拉取 `/auth/me`，成功后按上一次工作台恢复。 */
export async function restoreSession(): Promise<void> {
  if (session.ready) return
  if (restoring) return restoring
  const version = generation
  restoring = (async () => {
    session.restoring = true
    if (!session.token) {
      session.ready = true
      return
    }
    try {
      const user = parseUser(await authApi.me())
      if (version !== generation) return
      session.user = user
      const allowed = allowedWorkspaces()
      session.workspace = session.workspace && allowed.includes(session.workspace) ? session.workspace : (allowed[0] ?? null)
      if (session.workspace) writeStorage(WORKSPACE_KEY, session.workspace)
      session.ready = true
    } catch (error) {
      if (version === generation) {
        if (error instanceof ApiError && (error.unauthorized || error.forbidden)) clearSession()
        else session.ready = false
      }
      throw error
    } finally {
      session.restoring = false
      restoring = null
    }
  })()
  return restoring
}

export async function login(username: string, password: string): Promise<CurrentUser> {
  if (session.loginPending) throw new ApiError(0, 'DUPLICATE', '正在登录，请稍候。')
  session.loginPending = true
  session.loginError = ''
  clearSession()
  const version = generation
  try {
    const result = await authApi.login(username, password)
    if (!result?.access_token) throw new ApiError(0, 'BAD_LOGIN', '认证响应缺少访问令牌。')
    if (version !== generation) throw new ApiError(0, 'STALE', '会话已变更，请重新登录。')
    session.token = result.access_token
    writeStorage(TOKEN_KEY, result.access_token)
    const user = parseUser(result.user ?? (await authApi.me()))
    const allowed = workspacesForRoles(user.roles as string[])
    if (!allowed.length) {
      clearSession()
      throw new ApiError(403, 'NO_ROLE', '当前账号没有可用的业务角色，请联系管理员。')
    }
    session.user = user
    session.workspace = allowed[0]
    session.ready = true
    writeStorage(WORKSPACE_KEY, session.workspace)
    return user
  } finally {
    session.loginPending = false
  }
}

export async function logout(): Promise<void> {
  try {
    if (session.token) await authApi.logout()
  } catch {
    /* 退出失败也要清本地状态，避免卡在已失效会话里。 */
  } finally {
    clearSession()
  }
}

export function setWorkspace(workspace: Workspace): void {
  if (!allowedWorkspaces().includes(workspace)) return
  session.workspace = workspace
  writeStorage(WORKSPACE_KEY, workspace)
}
