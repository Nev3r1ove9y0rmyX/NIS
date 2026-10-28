<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { workspaceMeta, workspacesForRoles, type Workspace } from '../api/types'
import { allowedWorkspaces, logout, session, workspacePath } from '../stores/session'

const props = defineProps<{ workspace: Workspace }>()
const router = useRouter()
const meta = computed(() => workspaceMeta[props.workspace])
const available = computed(() => allowedWorkspaces())
/** 侧栏固定展示四个业务环节，帮助演示时说明协同链；当前工作台高亮。 */
const flow = workspacesForRoles(['reconnaissance', 'analyst', 'decision_maker', 'executor'])

function switchTo(target: Workspace) {
  if (target === props.workspace) return
  void router.push(workspacePath(target))
}

async function signOut() {
  await logout()
  void router.replace({ path: '/login' })
}
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <RouterLink to="/" class="brand">N<span class="brand-dot">◈</span>IS<small>协同调度信息系统</small></RouterLink>
      <span class="sidebar-label">工作空间 / WORKSPACE</span>
      <nav aria-label="角色工作台">
        <button
          v-for="item in available"
          :key="item"
          :class="{ active: workspace === item }"
          @click="switchTo(item)"
        >
          <span class="nav-number">{{ String(available.indexOf(item) + 1).padStart(2, '0') }}</span>
          <span>{{ workspaceMeta[item].title }}</span>
          <span v-if="workspace === item" class="nav-arrow" aria-hidden="true">↗</span>
        </button>
      </nav>

      <div class="sidebar-flow">
        <span class="sidebar-label">协同闭环 / OODA</span>
        <div v-for="item in flow" :key="item" :class="{ current: workspace === item }">
          <span class="flow-dot"></span>{{ workspaceMeta[item].name }}
          <small>{{ workspaceMeta[item].stage.split(' / ')[1] }}</small>
        </div>
      </div>

      <div class="sidebar-bottom">
        <span class="little-dot"></span>真实接口 · {{ session.user?.organization?.name || '未归属组织' }}
        <small>{{ session.user?.username }} / NIS</small>
      </div>
    </aside>

    <div class="main-shell">
      <header class="topbar">
        <div class="breadcrumb">协同调度 <span>/</span> {{ meta.title }}</div>
        <div class="topbar-right">
          <span class="environment-tag">{{ meta.stage }}</span>
          <div class="user-avatar">{{ (session.user?.display_name || '?').slice(0, 1) }}</div>
          <div class="user-label">
            <strong>{{ session.user?.display_name }}</strong>
            <small>
              {{ session.user?.roles.join(' / ') }}
              <template v-if="session.user && session.user.roles.length > 1">· 角色上下文：{{ session.workspace }}</template>
            </small>
          </div>
          <button class="text-button" @click="signOut">退出</button>
        </div>
      </header>
      <main class="workspace-main">
        <slot />
        <footer class="workspace-footer">
          <span>NIS · 协同调度信息系统</span>
          <span>人在回路 / 每一步有据可循</span>
        </footer>
      </main>
    </div>
  </div>
</template>
