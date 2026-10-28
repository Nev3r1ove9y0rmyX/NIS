import { createRouter, createWebHistory, type RouteLocationNormalized } from 'vue-router'
import {
  allowedWorkspaces,
  homePath,
  restoreSession,
  session,
  setWorkspace,
} from '../stores/session'
import type { Workspace as WorkspaceType } from '../api/types'
import LoginView from '../views/LoginView.vue'
import ReconWorkspace from '../views/ReconWorkspace.vue'
import AnalysisWorkspace from '../views/AnalysisWorkspace.vue'
import DecisionWorkspace from '../views/DecisionWorkspace.vue'
import ExecutionWorkspace from '../views/ExecutionWorkspace.vue'
import AuditView from '../views/AuditView.vue'
import MessageView from '../views/MessageView.vue'

/**
 * 路由表与守卫。
 *
 * 规则（frontend/README.md、docs/rbac.md 第 6 节）：
 * 1. 受保护页面先恢复会话，再判断工作台是否属于当前用户的角色；
 * 2. 无权限显示明确页面，绝不出现空白屏；
 * 3. 401 清理会话并带 `next` 回到登录页，登录后跳回原地址。
 */

declare module 'vue-router' {
  interface RouteMeta {
    public?: boolean
    workspace?: WorkspaceType
    title?: string
  }
}

const workspaceViews = {
  recon: ReconWorkspace,
  analysis: AnalysisWorkspace,
  decision: DecisionWorkspace,
  execution: ExecutionWorkspace,
  audit: AuditView,
} as const

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: () => (session.user ? homePath() : '/login') },
    { path: '/login', component: LoginView, meta: { public: true, title: '登录' } },
    ...(Object.keys(workspaceViews) as WorkspaceType[]).map(workspace => ({
      path: `/w/${workspace}`,
      component: workspaceViews[workspace],
      meta: { workspace, title: workspace },
    })),
    {
      path: '/forbidden',
      component: MessageView,
      props: {
        code: '403',
        title: '当前角色无权进入这个工作台',
        message: '你登录的身份没有该角色的授权。请切换到自己的工作台，或联系管理员核对角色分配。',
      },
      meta: { public: true },
    },
    {
      path: '/unavailable',
      component: MessageView,
      props: {
        code: '503',
        title: '暂时无法恢复会话',
        message: '身份服务没有响应，页面不展示任何业务内容。请检查网络或后端服务后重试。',
      },
      meta: { public: true },
    },
    {
      path: '/no-role',
      component: MessageView,
      props: {
        code: '403',
        title: '账号尚未分配业务角色',
        message: '这个账号没有任何可用角色，因此没有可进入的工作台。请联系管理员在 IAM 中分配角色。',
      },
      meta: { public: true },
    },
    {
      path: '/:pathMatch(.*)*',
      component: MessageView,
      props: { code: '404', title: '页面不存在', message: '请检查链接，或返回自己的工作台。' },
      meta: { public: true },
    },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

export async function guard(to: RouteLocationNormalized): Promise<boolean | string | { path: string; query?: Record<string, string> }> {
  if (to.meta.public) return true

  try {
    await restoreSession()
  } catch {
    if (!session.token) return { path: '/login', query: { next: to.fullPath } }
    return '/unavailable'
  }

  if (!session.token || !session.user) return { path: '/login', query: { next: to.fullPath } }

  const workspace = to.meta.workspace
  if (workspace) {
    if (!allowedWorkspaces().includes(workspace)) return '/forbidden'
    setWorkspace(workspace)
  }
  return true
}

router.beforeEach(guard)

window.addEventListener('nis:unauthorized', () => {
  const current = router.currentRoute.value
  if (current.meta.public) return
  void router.replace({ path: '/login', query: { expired: '1', next: current.fullPath } })
})
