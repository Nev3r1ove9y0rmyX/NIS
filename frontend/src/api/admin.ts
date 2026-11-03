/**
 * 系统管理接口封装（对应契约「管理」标签）。
 *
 * 覆盖四个能力：角色权限、用户角色（含限时）、在线用户与强制下线、账号设备绑定。
 * 与 `docs/onsign-acceptance.md` 的演示项一一对应，前端不发明字段。
 */

import { request } from './client'

export interface AdminRole {
  id: string
  code: string
  name: string
  is_system?: boolean
  permissions: string[]
}

export interface AdminPermission {
  code: string
  name: string
  domain: string
}

export interface AdminUser {
  id: string
  username: string
  display_name: string
  status: string
  organization_id?: string | null
}

export interface UserRoleBinding {
  role_code: string
  role_name?: string
  expires_at?: string | null
}

export interface OnlineUser {
  user_id: string
  username: string
  display_name: string
  online: boolean
  last_seen_at?: string | null
  last_ip?: string | null
  sessions?: number
}

export interface DeviceBinding {
  user_id: string
  allowed_ips: string[]
  allowed_macs: string[]
  enforced: boolean
}

function pageQuery(params: { page?: number; page_size?: number; status?: string; role_code?: string }): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const adminApi = {
  roles: () => request<{ items: AdminRole[] }>('/admin/roles'),

  permissions: () => request<{ items: AdminPermission[] }>('/admin/permissions'),

  replaceRolePermissions: (roleId: string, permissionCodes: string[]) =>
    request<{ role_id?: string; permission_codes?: string[] }>(
      `/admin/roles/${roleId}/permissions`,
      { method: 'PUT', body: { permission_codes: permissionCodes } },
    ),

  users: (query: { page?: number; page_size?: number; status?: string; role_code?: string } = {}) =>
    request<{ items: AdminUser[]; total: number }>(`/admin/users${pageQuery(query)}`),

  userRoles: (userId: string) =>
    request<{ items: UserRoleBinding[] }>(`/admin/users/${userId}/roles`),

  assignRole: (userId: string, roleCode: string, expiresAt?: string | null) =>
    request<{ items?: UserRoleBinding[] }>(`/admin/users/${userId}/roles`, {
      method: 'POST',
      body: { role_code: roleCode, expires_at: expiresAt || undefined },
    }),

  removeRole: (userId: string, roleCode: string) =>
    request<void>(`/admin/users/${userId}/roles/${roleCode}`, { method: 'DELETE' }),

  onlineUsers: () =>
    request<{ items: OnlineUser[]; total: number; window_minutes?: number }>('/admin/online-users'),

  forceLogout: (userId: string) =>
    request<{ user_id: string; revoked_sessions: number; revoked_at?: string }>(
      `/admin/users/${userId}/force-logout`,
      { method: 'POST' },
    ),

  deviceBinding: (userId: string) => request<DeviceBinding>(`/admin/users/${userId}/device-binding`),

  setDeviceBinding: (userId: string, allowedIps: string[], allowedMacs: string[]) =>
    request<DeviceBinding>(`/admin/users/${userId}/device-binding`, {
      method: 'PUT',
      body: { allowed_ips: allowedIps, allowed_macs: allowedMacs },
    }),
}
