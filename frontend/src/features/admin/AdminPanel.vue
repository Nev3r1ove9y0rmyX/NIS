<script setup lang="ts">
/**
 * 系统管理面板：一个页面覆盖四个验收点。
 *
 * 1) 角色权限：勾选/取消单项权限 → 立即生效（基础用例 10 + 扩展「细粒度权限」）；
 * 2) 用户与角色：授予角色时可设到期时间（扩展「限时角色」）；
 * 3) 在线用户：查看在线状态并强制下线（扩展「在线状态与强制下线」）；
 * 4) 设备绑定：账号绑定 IP / MAC（扩展「账号与终端绑定」）。
 *
 * 前端只调用契约里的管理接口，不发明字段；所有写操作成功后重新拉取数据。
 */
import { computed, onMounted, ref } from 'vue'
import { ApiError } from '../../api/client'
import {
  adminApi,
  type AdminPermission,
  type AdminRole,
  type AdminUser,
  type DeviceBinding,
  type OnlineUser,
  type UserRoleBinding,
} from '../../api/admin'
import { pushToast } from '../../stores/toast'
import { formatFull } from '../../utils/format'

type Tab = 'roles' | 'users' | 'online' | 'devices'

const tab = ref<Tab>('roles')
const tabs: { key: Tab; label: string }[] = [
  { key: 'roles', label: '角色权限' },
  { key: 'users', label: '用户与角色' },
  { key: 'online', label: '在线用户' },
  { key: 'devices', label: '设备绑定' },
]

const loading = ref(false)
const error = ref<string | null>(null)

const roles = ref<AdminRole[]>([])
const permissions = ref<AdminPermission[]>([])
const activeRoleId = ref<string>('')
const draftPermissions = ref<Set<string>>(new Set())
const savingPermissions = ref(false)

const users = ref<AdminUser[]>([])
const activeUserId = ref<string>('')
const userRoles = ref<UserRoleBinding[]>([])
const assignRoleCode = ref<string>('')
const assignExpiresAt = ref<string>('')

const online = ref<OnlineUser[]>([])
const deviceTargetId = ref<string>('')
const deviceBinding = ref<DeviceBinding | null>(null)
const deviceIps = ref('')
const deviceMacs = ref('')
const savingDevice = ref(false)

const activeRole = computed(() => roles.value.find(item => item.id === activeRoleId.value) || null)
const activeUser = computed(() => users.value.find(item => item.id === activeUserId.value) || null)
const permissionGroups = computed(() => {
  const groups = new Map<string, AdminPermission[]>()
  for (const item of permissions.value) {
    const list = groups.get(item.domain) || []
    list.push(item)
    groups.set(item.domain, list)
  }
  return [...groups.entries()].map(([domain, items]) => ({ domain, items }))
})

function fail(cause: unknown, fallback: string) {
  error.value = cause instanceof ApiError ? cause.message : fallback
}

async function loadRoles() {
  const [rolePage, permissionPage] = await Promise.all([adminApi.roles(), adminApi.permissions()])
  roles.value = rolePage.items
  permissions.value = permissionPage.items
  if (!activeRoleId.value && roles.value.length) {
    selectRole(roles.value[0].id)
  }
}

function selectRole(roleId: string) {
  activeRoleId.value = roleId
  const role = roles.value.find(item => item.id === roleId)
  draftPermissions.value = new Set(role?.permissions ?? [])
}

function togglePermission(code: string) {
  const next = new Set(draftPermissions.value)
  if (next.has(code)) next.delete(code)
  else next.add(code)
  draftPermissions.value = next
}

async function savePermissions() {
  if (!activeRole.value) return
  savingPermissions.value = true
  try {
    await adminApi.replaceRolePermissions(activeRole.value.id, [...draftPermissions.value])
    pushToast(`已保存 ${activeRole.value.name} 的权限（${draftPermissions.value.size} 项）`, 'success')
    await loadRoles()
    selectRole(activeRole.value.id)
  } catch (cause) {
    fail(cause, '保存权限失败')
  } finally {
    savingPermissions.value = false
  }
}

async function loadUsers() {
  const page = await adminApi.users({ page: 1, page_size: 50 })
  users.value = page.items
  if (!activeUserId.value && users.value.length) {
    await selectUser(users.value[0].id)
  }
}

async function selectUser(userId: string) {
  activeUserId.value = userId
  userRoles.value = []
  if (!userId) return
  await Promise.all([loadUserRoles(userId), loadDeviceBinding(userId)])
}

async function loadUserRoles(userId: string) {
  try {
    const page = await adminApi.userRoles(userId)
    userRoles.value = page.items
  } catch (cause) {
    fail(cause, '读取用户角色失败')
  }
}

async function assignRole() {
  if (!activeUserId.value || !assignRoleCode.value) return
  try {
    await adminApi.assignRole(activeUserId.value, assignRoleCode.value, assignExpiresAt.value || null)
    pushToast(`已授予角色 ${assignRoleCode.value}`, 'success')
    assignRoleCode.value = ''
    assignExpiresAt.value = ''
    await loadUserRoles(activeUserId.value)
  } catch (cause) {
    fail(cause, '授予角色失败')
  }
}

async function removeRole(code: string) {
  if (!activeUserId.value) return
  try {
    await adminApi.removeRole(activeUserId.value, code)
    pushToast(`已移除角色 ${code}`, 'success')
    await loadUserRoles(activeUserId.value)
  } catch (cause) {
    fail(cause, '移除角色失败')
  }
}

async function loadOnline() {
  try {
    const page = await adminApi.onlineUsers()
    online.value = page.items
  } catch (cause) {
    fail(cause, '读取在线用户失败')
  }
}

async function forceLogout(item: OnlineUser) {
  try {
    const result = await adminApi.forceLogout(item.user_id)
    pushToast(`已强制下线 ${item.username}（吊销 ${result.revoked_sessions ?? 0} 个会话）`, 'success')
    await loadOnline()
  } catch (cause) {
    fail(cause, '强制下线失败')
  }
}

async function loadDeviceBinding(userId: string) {
  try {
    deviceBinding.value = await adminApi.deviceBinding(userId)
    deviceIps.value = deviceBinding.value.allowed_ips.join(', ')
    deviceMacs.value = deviceBinding.value.allowed_macs.join(', ')
  } catch (cause) {
    fail(cause, '读取设备绑定失败')
  }
}

async function saveDeviceBinding() {
  if (!activeUserId.value) return
  savingDevice.value = true
  try {
    const ips = deviceIps.value.split(',').map(v => v.trim()).filter(Boolean)
    const macs = deviceMacs.value.split(',').map(v => v.trim()).filter(Boolean)
    deviceBinding.value = await adminApi.setDeviceBinding(activeUserId.value, ips, macs)
    pushToast(
      deviceBinding.value.enforced
        ? `已绑定 ${ips.length} 个 IP / ${macs.length} 个 MAC`
        : '已解除绑定（该账号可在任意终端登录）',
      'success',
    )
  } catch (cause) {
    fail(cause, '保存设备绑定失败')
  } finally {
    savingDevice.value = false
  }
}

async function switchTab(next: Tab) {
  tab.value = next
  error.value = null
  if (next === 'roles') await loadRoles()
  if (next === 'users') await loadUsers()
  if (next === 'online') await loadOnline()
  if (next === 'devices') await loadUsers()
}

onMounted(async () => {
  loading.value = true
  try {
    await loadRoles()
  } catch (cause) {
    fail(cause, '初始化失败')
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <section class="admin-panel">
    <div class="admin-tabs" role="tablist" aria-label="系统管理">
      <button
        v-for="item in tabs"
        :key="item.key"
        :class="{ active: tab === item.key }"
        role="tab"
        :aria-selected="tab === item.key"
        @click="switchTab(item.key)"
      >
        {{ item.label }}
      </button>
    </div>

    <p v-if="error" class="admin-error">{{ error }}</p>

    <!-- 角色权限 -->
    <div v-if="tab === 'roles'" class="admin-body">
      <aside class="admin-list">
        <button
          v-for="role in roles"
          :key="role.id"
          :class="{ active: role.id === activeRoleId }"
          @click="selectRole(role.id)"
        >
          <strong>{{ role.name }}</strong>
          <small>{{ role.code }} · {{ role.permissions.length }} 项权限</small>
        </button>
      </aside>

      <div class="admin-content">
        <header class="admin-head">
          <div>
            <h3>{{ activeRole?.name || '选择角色' }}</h3>
            <p class="muted">勾选即生效；保存后该角色下的所有账号立即按新权限访问。</p>
          </div>
          <button class="primary" :disabled="!activeRole || savingPermissions" @click="savePermissions">
            {{ savingPermissions ? '保存中…' : '保存权限' }}
          </button>
        </header>

        <div v-for="group in permissionGroups" :key="group.domain" class="perm-group">
          <div class="perm-group-title">{{ group.domain }}</div>
          <label v-for="perm in group.items" :key="perm.code" class="perm-item">
            <input
              type="checkbox"
              :checked="draftPermissions.has(perm.code)"
              @change="togglePermission(perm.code)"
            />
            <span>{{ perm.name }}</span>
            <code>{{ perm.code }}</code>
          </label>
        </div>
      </div>
    </div>

    <!-- 用户与角色 -->
    <div v-else-if="tab === 'users'" class="admin-body">
      <aside class="admin-list">
        <button
          v-for="user in users"
          :key="user.id"
          :class="{ active: user.id === activeUserId }"
          @click="selectUser(user.id)"
        >
          <strong>{{ user.display_name }}</strong>
          <small>{{ user.username }} · {{ user.status }}</small>
        </button>
      </aside>

      <div class="admin-content">
        <header class="admin-head">
          <div>
            <h3>{{ activeUser?.display_name || '选择用户' }}</h3>
            <p class="muted">授予角色时可设到期时间；到期后该角色自动失效，无需人工撤销。</p>
          </div>
        </header>

        <table class="admin-table">
          <thead>
            <tr><th>角色</th><th>到期时间</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="binding in userRoles" :key="binding.role_code">
              <td>{{ binding.role_name || binding.role_code }}</td>
              <td>{{ binding.expires_at ? formatFull(binding.expires_at) : '长期' }}</td>
              <td><button class="text-button" @click="removeRole(binding.role_code)">移除</button></td>
            </tr>
            <tr v-if="!userRoles.length"><td colspan="3" class="muted">暂无角色</td></tr>
          </tbody>
        </table>

        <div class="assign-row">
          <select v-model="assignRoleCode">
            <option value="">选择角色</option>
            <option v-for="role in roles" :key="role.id" :value="role.code">{{ role.name }}</option>
          </select>
          <input v-model="assignExpiresAt" type="datetime-local" aria-label="到期时间" />
          <button class="primary" :disabled="!activeUserId || !assignRoleCode" @click="assignRole">
            授予角色
          </button>
        </div>
      </div>
    </div>

    <!-- 在线用户 -->
    <div v-else-if="tab === 'online'" class="admin-content">
      <header class="admin-head">
        <div>
          <h3>在线用户</h3>
          <p class="muted">最近 5 分钟内有活动即视为在线；强制下线会吊销该账号全部会话。</p>
        </div>
        <button class="text-button" @click="loadOnline">刷新</button>
      </header>
      <table class="admin-table">
        <thead>
          <tr><th>账号</th><th>状态</th><th>最近活动</th><th>来源地址</th><th>会话数</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in online" :key="item.user_id">
            <td>{{ item.display_name }}<small class="muted"> / {{ item.username }}</small></td>
            <td>{{ item.online ? '在线' : '离线' }}</td>
            <td>{{ item.last_seen_at ? formatFull(item.last_seen_at) : '—' }}</td>
            <td>{{ item.last_ip || '—' }}</td>
            <td>{{ item.sessions ?? 1 }}</td>
            <td>
              <button class="text-button" :disabled="!item.online" @click="forceLogout(item)">
                强制下线
              </button>
            </td>
          </tr>
          <tr v-if="!online.length"><td colspan="6" class="muted">当前无在线用户</td></tr>
        </tbody>
      </table>
    </div>

    <!-- 设备绑定 -->
    <div v-else class="admin-body">
      <aside class="admin-list">
        <button
          v-for="user in users"
          :key="user.id"
          :class="{ active: user.id === activeUserId }"
          @click="selectUser(user.id)"
        >
          <strong>{{ user.display_name }}</strong>
          <small>{{ user.username }}</small>
        </button>
      </aside>

      <div class="admin-content">
        <header class="admin-head">
          <div>
            <h3>账号与终端绑定</h3>
            <p class="muted">填写后只有列表内的终端可登录；两项都留空表示解除绑定。</p>
          </div>
          <button class="primary" :disabled="!activeUserId || savingDevice" @click="saveDeviceBinding">
            {{ savingDevice ? '保存中…' : '保存绑定' }}
          </button>
        </header>

        <div class="bind-field">
          <label for="device-ips">允许的 IP（逗号分隔，可留空）</label>
          <input id="device-ips" v-model="deviceIps" placeholder="例如 192.168.146.1, 10.252.150.101" />
        </div>
        <div class="bind-field">
          <label for="device-macs">允许的 MAC（逗号分隔，可留空）</label>
          <input id="device-macs" v-model="deviceMacs" placeholder="例如 aa:bb:cc:dd:ee:ff" />
        </div>
        <p class="muted">
          当前状态：{{ deviceBinding?.enforced ? '已绑定（仅白名单终端可登录）' : '未绑定（任意终端可登录）' }}
        </p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.admin-panel {
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--paper);
  padding: 18px 20px 26px;
}
.admin-tabs {
  display: flex;
  gap: 8px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 12px;
  margin-bottom: 18px;
  flex-wrap: wrap;
}
.admin-tabs button {
  border: 1px solid transparent;
  background: transparent;
  padding: 7px 14px;
  border-radius: 6px;
  color: var(--muted);
}
.admin-tabs button.active {
  background: #eef4e6;
  border-color: #c9dcae;
  color: var(--ink);
  font-weight: 600;
}
.admin-error {
  margin: 0 0 12px;
  padding: 8px 12px;
  border-radius: 6px;
  background: #fdecea;
  color: #9b3a2a;
}
.admin-body {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  gap: 20px;
}
.admin-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 460px;
  overflow: auto;
}
.admin-list button {
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: #fbfcf9;
  padding: 8px 10px;
}
.admin-list button.active {
  border-color: var(--green);
  background: #f2f7ea;
}
.admin-list small {
  color: var(--muted);
  font-size: 11px;
}
.admin-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}
.admin-head h3 {
  margin: 0 0 4px;
  font-size: 16px;
}
.perm-group {
  margin-bottom: 14px;
}
.perm-group-title {
  font-size: 12px;
  letter-spacing: 1px;
  color: var(--muted);
  margin-bottom: 6px;
}
.perm-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 13px;
}
.perm-item code {
  color: var(--muted);
  font-size: 11px;
}
.admin-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.admin-table th,
.admin-table td {
  border-bottom: 1px solid var(--border);
  padding: 8px 10px;
  text-align: left;
}
.admin-table th {
  background: #f4f6f0;
  font-weight: 600;
}
.assign-row {
  display: flex;
  gap: 10px;
  margin-top: 16px;
  flex-wrap: wrap;
}
.assign-row select,
.assign-row input {
  min-width: 160px;
  width: auto;
}
.bind-field {
  margin-bottom: 14px;
}
.bind-field label {
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
  color: var(--muted);
}
</style>
