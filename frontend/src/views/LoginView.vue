<script setup lang="ts">
/**
 * 登录页（C-03）。
 *
 * 一次登录拿到全部角色与权限（/auth/login 已返回 user），随后按角色进入对应工作台。
 * 登录失败区分：账号密码错误、账号锁定、服务不可达；都不暴露后端内部信息。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '../api/client'
import { homePath, allowedWorkspaces, login, session, workspacePath } from '../stores/session'
import { workspaceMeta, type Workspace as WorkspaceType } from '../api/types'

const username = ref('')
const password = ref('')
const error = ref('')
const errorCode = ref('')
const busy = ref(false)
const route = useRoute()
const router = useRouter()

const expired = computed(() => route.query.expired === '1')
const demoAccounts = [
  { account: 'recon01', role: '侦察员', workspace: 'recon' as WorkspaceType },
  { account: 'analyst01', role: '分析员', workspace: 'analysis' as WorkspaceType },
  { account: 'dmaker01', role: '决策员', workspace: 'decision' as WorkspaceType },
  { account: 'exec01', role: '执行员', workspace: 'execution' as WorkspaceType },
]

/** 登录后回到原来的受保护地址（只接受本站站内路径）。 */
function nextTarget(workspaces: WorkspaceType[]): string {
  const next = typeof route.query.next === 'string' ? route.query.next : ''
  if (next.startsWith('/') && !next.startsWith('//')) {
    const workspace = next.startsWith('/w/') ? (next.slice(3).split('/')[0] as WorkspaceType) : null
    if (!workspace || workspaces.includes(workspace)) return next
  }
  return session.workspace ? workspacePath(session.workspace) : homePath()
}

async function submit() {
  if (busy.value) return
  error.value = ''
  errorCode.value = ''
  if (!username.value.trim() || !password.value) {
    error.value = '请填写用户名和密码。'
    return
  }
  busy.value = true
  try {
    await login(username.value.trim(), password.value)
    password.value = ''
    await router.replace(nextTarget(allowedWorkspaces()))
  } catch (cause) {
    if (cause instanceof ApiError) {
      error.value = cause.message
      errorCode.value = cause.code
    } else {
      error.value = '登录失败，请稍后重试。'
    }
  } finally {
    busy.value = false
  }
}

onMounted(() => {
  if (session.token && session.user) void router.replace(homePath())
})
</script>

<template>
  <main class="login-page">
    <section class="login-story">
      <a class="brand" href="/">N<span class="brand-dot">◈</span>IS <small>协同调度信息系统</small></a>
      <div class="story-body">
        <span class="eyebrow">NETWORKED INFORMATION SYSTEM</span>
        <h1>让信息成为判断，<br>让判断抵达行动。</h1>
        <p>侦察 · 分析 · 决策 · 执行<br>一条可追溯的协同链，一次经过确认的行动。</p>
        <div class="ooda-ring" aria-label="OODA 协同循环">
          <span>OBSERVE</span><b>OODA<i>HUMAN IN THE LOOP</i></b><span>ORIENT</span><span>DECIDE</span><span>ACT</span>
        </div>
        <ul class="login-roles">
          <li v-for="item in demoAccounts" :key="item.account">
            <strong>{{ workspaceMeta[item.workspace].name }}</strong>
            <span>{{ item.account }}</span>
          </li>
        </ul>
      </div>
      <footer>网络信息系统解构 / 课程项目 <span>01 — 04</span></footer>
    </section>

    <section class="login-panel">
      <div class="login-box">
        <span class="eyebrow">WELCOME TO NIS</span>
        <h2>登录协同工作台</h2>
        <p class="muted">使用团队分配的演示账号登录；角色决定你进入哪个工作台。</p>
        <p v-if="expired" class="notice" role="status">登录已失效，请重新登录。</p>

        <form @submit.prevent="submit">
          <label for="username">用户名</label>
          <input
            id="username"
            v-model="username"
            autocomplete="username"
            required
            maxlength="64"
            placeholder="例如 recon01"
            :disabled="busy"
          >
          <label for="password">密码</label>
          <input
            id="password"
            v-model="password"
            type="password"
            autocomplete="current-password"
            required
            maxlength="256"
            placeholder="请输入密码"
            :disabled="busy"
          >
          <p v-if="error" class="error-box" role="alert">{{ error }}</p>
          <p v-if="errorCode" class="muted">错误码：{{ errorCode }}</p>
          <button class="primary login-submit" :disabled="busy">
            {{ busy ? '正在验证身份…' : '登录工作台 →' }}
          </button>
        </form>

        <div class="login-footnote">
          <span class="little-dot"></span> 角色授权访问 · 关键操作人工确认
        </div>
        <p class="muted login-hint">
          口令由 <code>NIS_DEMO_PASSWORD</code> 注入，不写入仓库；演示前请由管理员在本地环境变量里设置。
        </p>
      </div>
    </section>
  </main>
</template>
