<script setup lang="ts">
/**
 * 执行员工作台（C-07）。
 *
 * 只看自己被告知的分配：接收 / 拒绝 / 开始 / 填写结果。
 * 页面上的按钮只是提示，服务端对每次状态转换都会重新校验版本与资源范围。
 */
import { onMounted, ref, watch } from 'vue'
import { assignmentApi } from '../api/endpoints'
import {
  assignmentStatusOptions,
  priorityNames,
  workspaceMeta,
  type Assignment,
} from '../api/types'
import AppShell from '../components/AppShell.vue'
import DataState from '../components/DataState.vue'
import StatusPill from '../components/StatusPill.vue'
import AssignmentPanel from '../features/execution/AssignmentPanel.vue'
import { usePagedList } from '../composables/usePagedList'
import { formatDateTime, truncate } from '../utils/format'

const meta = workspaceMeta.execution
const statusFilter = ref('')
const counts = ref({ pending: 0, executing: 0, completed: 0, rejected: 0 })

const { state, load, goto, pages, reset } = usePagedList<Assignment>(query =>
  assignmentApi.list({ ...query, status: statusFilter.value || undefined }),
)

const panelOpen = ref(false)
const activeId = ref<string | null>(null)

async function loadCounts() {
  try {
    const [pending, executing, completed, rejected] = await Promise.all([
      assignmentApi.list({ status: 'pending', page_size: 1 }),
      assignmentApi.list({ status: 'executing', page_size: 1 }),
      assignmentApi.list({ status: 'completed', page_size: 1 }),
      assignmentApi.list({ status: 'rejected', page_size: 1 }),
    ])
    counts.value = {
      pending: pending.total,
      executing: executing.total,
      completed: completed.total,
      rejected: rejected.total,
    }
  } catch {
    counts.value = { pending: 0, executing: 0, completed: 0, rejected: 0 }
  }
}

async function refresh() {
  await Promise.all([load(state.page, { silent: true }), loadCounts()])
}

function open(id: string) {
  activeId.value = id
  panelOpen.value = true
}

watch(statusFilter, async () => {
  reset()
  await load(1)
})

onMounted(refresh)
</script>

<template>
  <AppShell workspace="execution">
    <section class="page-heading">
      <div>
        <div class="eyebrow">{{ meta.stage }}</div>
        <h1>{{ meta.title }}<span class="heading-dot">.</span></h1>
        <p>{{ meta.description }}</p>
      </div>
      <button class="new-button" disabled title="执行任务由决策员下达">{{ meta.action }}</button>
    </section>

    <section class="metric-grid" aria-label="执行任务概况">
      <article>
        <span>待接收</span>
        <strong>{{ String(counts.pending).padStart(2, '0') }}</strong>
        <small>需要你确认接收或拒绝</small><i>◷</i>
      </article>
      <article>
        <span>执行中</span>
        <strong>{{ String(counts.executing).padStart(2, '0') }}</strong>
        <small>已接收并开始执行</small><i>↗</i>
      </article>
      <article>
        <span>本页任务</span>
        <strong>{{ String(state.total).padStart(2, '0') }}</strong>
        <small>当前筛选下的总数</small><i>▤</i>
      </article>
      <article class="accent-metric">
        <span>已完成</span>
        <strong>{{ String(counts.completed).padStart(2, '0') }}</strong>
        <small>已提交结果</small><i>✓</i>
      </article>
    </section>

    <section class="records-panel">
      <div class="panel-heading">
        <div class="tabs" role="tablist" aria-label="数据视图">
          <button role="tab" aria-selected="true" class="active">{{ meta.listLabel }}<span>{{ state.total }}</span></button>
        </div>
        <span class="panel-caption">只显示分配给你的任务</span>
      </div>

      <div class="table-toolbar">
        <div class="filters">
          <select v-model="statusFilter" aria-label="按状态筛选任务">
            <option value="">全部状态</option>
            <option v-for="option in assignmentStatusOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </div>
        <div class="actions"><button aria-label="刷新列表" @click="refresh">↻ 刷新</button></div>
      </div>

      <DataState
        :loading="state.loading"
        :error="state.error"
        :empty="state.loaded && !state.items.length"
        empty-title="没有分配给你的执行任务"
        empty-hint="决策员下达指令并选择你为执行员后，任务会出现在这里。"
        @retry="refresh"
      >
        <div class="table-scroll">
          <table>
            <thead>
              <tr><th>任务 / 指令内容</th><th>优先级</th><th>状态</th><th>截止时间</th><th>接收时间</th><th class="align-right">操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="item in state.items" :key="item.id">
                <td class="record-title-cell">
                  <button class="record-title" @click="open(item.id)">{{ item.command_title_snapshot }}</button>
                  <small>{{ truncate(item.command_content_snapshot, 52) }}</small>
                </td>
                <td><span class="priority" :class="item.priority"><span></span>{{ priorityNames[item.priority] }}</span></td>
                <td><StatusPill kind="assignment" :status="item.status" /></td>
                <td class="date-cell">{{ formatDateTime(item.deadline) }}</td>
                <td class="date-cell">{{ formatDateTime(item.accepted_at) }}</td>
                <td class="align-right">
                  <button class="table-action" @click="open(item.id)">
                    {{ item.status === 'pending' ? '接收 / 拒绝 ↗' : '查看 / 反馈 ↗' }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="pagination">
          <span>共 {{ state.total }} 条 · 每页 {{ state.pageSize }} 条</span>
          <div class="actions">
            <button aria-label="上一页" :disabled="state.page <= 1" @click="goto(state.page - 1)">←</button>
            <span>{{ state.page }} / {{ pages() }}</span>
            <button aria-label="下一页" :disabled="state.page >= pages()" @click="goto(state.page + 1)">→</button>
          </div>
        </div>
      </DataState>
    </section>

    <section class="next-step">
      <span>下一步 / NEXT STEP</span>
      <p>{{ meta.nextStep }}</p>
      <span class="next-arrow">→</span>
    </section>

    <AssignmentPanel :open="panelOpen" :assignment-id="activeId" @close="panelOpen = false" @changed="refresh" />
  </AppShell>
</template>
