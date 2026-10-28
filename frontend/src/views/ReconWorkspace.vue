<script setup lang="ts">
/**
 * 侦察员工作台（C-04）。
 *
 * 覆盖：我的记录列表（服务端分页 + 状态筛选）、新建/保存草稿、提交并指派分析员、
 * 详情查看、证据元数据与「下载受控文件」的失败提示。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { reconApi } from '../api/endpoints'
import {
  credibilityNames,
  priorityNames,
  reconStatusOptions,
  workspaceMeta,
  type ReconRecord,
} from '../api/types'
import AppShell from '../components/AppShell.vue'
import DataState from '../components/DataState.vue'
import StatusPill from '../components/StatusPill.vue'
import ReconPanel from '../features/recon/ReconPanel.vue'
import { usePagedList } from '../composables/usePagedList'
import { session } from '../stores/session'
import { formatDateTime, truncate } from '../utils/format'

const meta = workspaceMeta.recon
const statusFilter = ref('')
const keyword = ref('')
const counts = ref({ draft: 0, assigned: 0, analyzed: 0 })

const { state, load, goto, pages, reset } = usePagedList<ReconRecord>(query =>
  reconApi.list({ ...query, status: statusFilter.value || undefined }),
)

const panelOpen = ref(false)
const activeId = ref<string | null>(null)

const visible = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  if (!text) return state.items
  return state.items.filter(item =>
    `${item.record_no} ${item.title} ${item.source_ref ?? ''}`.toLowerCase().includes(text),
  )
})

async function loadCounts() {
  try {
    const [draft, assigned, analyzed] = await Promise.all([
      reconApi.list({ status: 'draft', page_size: 1 }),
      reconApi.list({ status: 'assigned', page_size: 1 }),
      reconApi.list({ status: 'analyzed', page_size: 1 }),
    ])
    counts.value = { draft: draft.total, assigned: assigned.total, analyzed: analyzed.total }
  } catch {
    counts.value = { draft: 0, assigned: 0, analyzed: 0 }
  }
}

function openNew() {
  activeId.value = null
  panelOpen.value = true
}

function openRecord(id: string) {
  activeId.value = id
  panelOpen.value = true
}

async function refresh() {
  await Promise.all([load(state.page, { silent: true }), loadCounts()])
}

watch(statusFilter, async () => {
  reset()
  await load(1)
})

onMounted(async () => {
  await refresh()
})
</script>

<template>
  <AppShell workspace="recon">
    <section class="page-heading">
      <div>
        <div class="eyebrow">{{ meta.stage }}</div>
        <h1>{{ meta.title }}<span class="heading-dot">.</span></h1>
        <p>{{ meta.description }}</p>
      </div>
      <button class="primary new-button" @click="openNew"><span>＋</span>{{ meta.action }}</button>
    </section>

    <section class="metric-grid" aria-label="我的侦察记录概况">
      <article>
        <span>本页记录</span>
        <strong>{{ String(state.total).padStart(2, '0') }}</strong>
        <small>服务端按「本人创建」过滤</small><i>↗</i>
      </article>
      <article>
        <span>草稿</span>
        <strong>{{ String(counts.draft).padStart(2, '0') }}</strong>
        <small>仅你能编辑，未进入流转</small><i>▤</i>
      </article>
      <article>
        <span>待分析</span>
        <strong>{{ String(counts.assigned).padStart(2, '0') }}</strong>
        <small>已指派分析员</small><i>◷</i>
      </article>
      <article class="accent-metric">
        <span>已分析</span>
        <strong>{{ String(counts.analyzed).padStart(2, '0') }}</strong>
        <small>分析员已完成研判</small><i>✓</i>
      </article>
    </section>

    <section class="records-panel">
      <div class="panel-heading">
        <div class="tabs" role="tablist" aria-label="数据视图">
          <button role="tab" aria-selected="true" class="active">{{ meta.listLabel }}<span>{{ state.total }}</span></button>
        </div>
        <span class="panel-caption">当前身份：{{ session.user?.display_name }}（{{ session.user?.organization?.name }}）</span>
      </div>

      <div class="table-toolbar">
        <div class="filters">
          <label class="search-field">
            <span aria-hidden="true">⌕</span>
            <input v-model="keyword" type="search" aria-label="搜索记录" placeholder="搜索编号、标题或来源">
          </label>
          <select v-model="statusFilter" aria-label="按状态筛选">
            <option value="">全部状态</option>
            <option v-for="option in reconStatusOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </div>
        <div class="actions">
          <button aria-label="刷新列表" @click="refresh">↻ 刷新</button>
        </div>
      </div>

      <DataState
        :loading="state.loading"
        :error="state.error"
        :empty="state.loaded && !visible.length"
        empty-title="还没有侦察记录"
        empty-hint="点击「新建侦察记录」开始第一条；保存草稿后会立刻出现在列表里。"
        @retry="refresh"
      >
        <template #empty-action>
          <button class="primary" @click="openNew">新建侦察记录</button>
        </template>

        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>记录 / 摘要</th>
                <th>来源</th>
                <th>可信度</th>
                <th>优先级</th>
                <th>当前状态</th>
                <th>更新时间</th>
                <th class="align-right">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in visible" :key="item.id">
                <td class="record-title-cell">
                  <button class="record-title" @click="openRecord(item.id)">{{ item.title }}</button>
                  <small>{{ item.record_no }} · {{ truncate(item.content, 46) }}</small>
                </td>
                <td><span class="source-cell" :title="item.source_ref || ''">{{ item.source_ref || '未填写' }}</span></td>
                <td>{{ credibilityNames[item.credibility] }}</td>
                <td><span class="priority" :class="item.priority"><span></span>{{ priorityNames[item.priority] }}</span></td>
                <td><StatusPill kind="recon" :status="item.status" /></td>
                <td class="date-cell">{{ formatDateTime(item.updated_at) }}</td>
                <td class="align-right">
                  <button class="table-action" @click="openRecord(item.id)">
                    {{ item.status === 'draft' ? '继续编辑 ↗' : '查看详情 ↗' }}
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

    <ReconPanel
      :open="panelOpen"
      :record-id="activeId"
      @close="panelOpen = false"
      @changed="refresh"
    />
  </AppShell>
</template>
