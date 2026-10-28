<script setup lang="ts">
/**
 * 分析员工作台（C-05）。
 *
 * 两个视图：
 * 1. 待分析侦察记录：只列出服务端指派给本人的记录（`recon:read_assigned`）；
 * 2. 我的分析报告：草稿可编辑，提交后进入「已提交待研判」。
 *
 * AI 建议在报告面板里处理，必须逐条接受/修改/舍弃后提交才会放行。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { reconApi, reportApi } from '../api/endpoints'
import {
  priorityNames,
  reconStatusNames,
  reportStatusOptions,
  riskNames,
  workspaceMeta,
  type AnalysisReport,
  type ReconRecord,
} from '../api/types'
import AppShell from '../components/AppShell.vue'
import DataState from '../components/DataState.vue'
import StatusPill from '../components/StatusPill.vue'
import ReconPanel from '../features/recon/ReconPanel.vue'
import ReportPanel from '../features/analysis/ReportPanel.vue'
import { usePagedList } from '../composables/usePagedList'
import { formatDateTime, truncate } from '../utils/format'

const meta = workspaceMeta.analysis
const tab = ref<'records' | 'reports'>('records')
const reportFilter = ref('')
const counts = ref({ assigned: 0, draft: 0, decided: 0 })

const recordsList = usePagedList<ReconRecord>(query => reconApi.list({ ...query, status: 'assigned' }))
const reportsList = usePagedList<AnalysisReport>(query =>
  reportApi.list({ ...query, status: reportFilter.value || undefined }),
)

const recordOpen = ref(false)
const recordId = ref<string | null>(null)
const reportOpen = ref(false)
const reportId = ref<string | null>(null)
const seedRecordId = ref<string | null>(null)

const reportsEmptyTitle = computed(() =>
  reportFilter.value ? '没有符合该状态的报告' : '还没有分析报告',
)

async function loadCounts() {
  try {
    const [assigned, draft, decided] = await Promise.all([
      reconApi.list({ status: 'assigned', page_size: 1 }),
      reportApi.list({ status: 'draft', page_size: 1 }),
      reportApi.list({ status: 'decided', page_size: 1 }),
    ])
    counts.value = { assigned: assigned.total, draft: draft.total, decided: decided.total }
  } catch {
    counts.value = { assigned: 0, draft: 0, decided: 0 }
  }
}

async function refresh() {
  await Promise.all([
    recordsList.load(recordsList.state.page, { silent: true }),
    reportsList.load(reportsList.state.page, { silent: true }),
    loadCounts(),
  ])
}

function openRecord(id: string) {
  recordId.value = id
  recordOpen.value = true
}

function openReport(id: string | null, seed: string | null = null) {
  reportId.value = id
  seedRecordId.value = seed
  reportOpen.value = true
}

function writeReportFor(recordIdValue: string) {
  recordOpen.value = false
  openReport(null, recordIdValue)
}

watch(reportFilter, async () => {
  reportsList.reset()
  await reportsList.load(1)
})

onMounted(refresh)
</script>

<template>
  <AppShell workspace="analysis">
    <section class="page-heading">
      <div>
        <div class="eyebrow">{{ meta.stage }}</div>
        <h1>{{ meta.title }}<span class="heading-dot">.</span></h1>
        <p>{{ meta.description }}</p>
      </div>
      <button class="primary new-button" @click="openReport(null)"><span>＋</span>{{ meta.action }}</button>
    </section>

    <section class="metric-grid" aria-label="分析任务概况">
      <article>
        <span>待分析记录</span>
        <strong>{{ String(counts.assigned).padStart(2, '0') }}</strong>
        <small>服务端指派给本人</small><i>◷</i>
      </article>
      <article>
        <span>报告草稿</span>
        <strong>{{ String(counts.draft).padStart(2, '0') }}</strong>
        <small>仅你能编辑</small><i>▤</i>
      </article>
      <article>
        <span>本页报告</span>
        <strong>{{ String(reportsList.state.total).padStart(2, '0') }}</strong>
        <small>按状态筛选后的总数</small><i>↗</i>
      </article>
      <article class="accent-metric">
        <span>已决策</span>
        <strong>{{ String(counts.decided).padStart(2, '0') }}</strong>
        <small>决策员已下达指令</small><i>✓</i>
      </article>
    </section>

    <section class="records-panel">
      <div class="panel-heading">
        <div class="tabs" role="tablist" aria-label="数据视图">
          <button role="tab" :aria-selected="tab === 'records'" :class="{ active: tab === 'records' }" @click="tab = 'records'">
            待分析侦察记录<span>{{ counts.assigned }}</span>
          </button>
          <button role="tab" :aria-selected="tab === 'reports'" :class="{ active: tab === 'reports' }" @click="tab = 'reports'">
            {{ meta.listLabel }}<span>{{ reportsList.state.total }}</span>
          </button>
        </div>
        <span class="panel-caption">AI 内容未经人工确认不能提交</span>
      </div>

      <template v-if="tab === 'records'">
        <div class="table-toolbar">
          <div class="filters"><span class="muted">按可信度与优先级判断先处理哪一条</span></div>
          <div class="actions"><button aria-label="刷新列表" @click="refresh">↻ 刷新</button></div>
        </div>

        <DataState
          :loading="recordsList.state.loading"
          :error="recordsList.state.error"
          :empty="recordsList.state.loaded && !recordsList.state.items.length"
          empty-title="没有指派给你的记录"
          empty-hint="侦察员提交并指派后，记录会出现在这里。"
          @retry="refresh"
        >
          <div class="table-scroll">
            <table>
              <thead>
                <tr><th>记录 / 摘要</th><th>来源</th><th>可信度</th><th>优先级</th><th>状态</th><th>提交时间</th><th class="align-right">操作</th></tr>
              </thead>
              <tbody>
                <tr v-for="item in recordsList.state.items" :key="item.id">
                  <td class="record-title-cell">
                    <button class="record-title" @click="openRecord(item.id)">{{ item.title }}</button>
                    <small>{{ item.record_no }} · {{ truncate(item.content, 46) }}</small>
                  </td>
                  <td><span class="source-cell">{{ item.source_ref || '未填写' }}</span></td>
                  <td>{{ item.credibility }}</td>
                  <td><span class="priority" :class="item.priority"><span></span>{{ priorityNames[item.priority] }}</span></td>
                  <td><StatusPill kind="recon" :status="item.status" /></td>
                  <td class="date-cell">{{ formatDateTime(item.submitted_at) }}</td>
                  <td class="align-right">
                    <button class="table-action" @click="openRecord(item.id)">查看 ↗</button>
                    <button class="table-action" @click="writeReportFor(item.id)">写报告 ↗</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="pagination">
            <span>共 {{ recordsList.state.total }} 条 · {{ reconStatusNames.assigned }}</span>
            <div class="actions">
              <button aria-label="上一页" :disabled="recordsList.state.page <= 1" @click="recordsList.goto(recordsList.state.page - 1)">←</button>
              <span>{{ recordsList.state.page }} / {{ recordsList.pages() }}</span>
              <button aria-label="下一页" :disabled="recordsList.state.page >= recordsList.pages()" @click="recordsList.goto(recordsList.state.page + 1)">→</button>
            </div>
          </div>
        </DataState>
      </template>

      <template v-else>
        <div class="table-toolbar">
          <div class="filters">
            <select v-model="reportFilter" aria-label="按状态筛选报告">
              <option value="">全部状态</option>
              <option v-for="option in reportStatusOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
          </div>
          <div class="actions"><button aria-label="刷新列表" @click="refresh">↻ 刷新</button></div>
        </div>

        <DataState
          :loading="reportsList.state.loading"
          :error="reportsList.state.error"
          :empty="reportsList.state.loaded && !reportsList.state.items.length"
          :empty-title="reportsEmptyTitle"
          empty-hint="选择一条待分析记录后可以立即写报告。"
          @retry="refresh"
        >
          <template #empty-action>
            <button class="primary" @click="openReport(null)">编写分析报告</button>
          </template>

          <div class="table-scroll">
            <table>
              <thead>
                <tr><th>报告 / 关键发现</th><th>引用记录</th><th>风险</th><th>优先级</th><th>状态</th><th>更新时间</th><th class="align-right">操作</th></tr>
              </thead>
              <tbody>
                <tr v-for="item in reportsList.state.items" :key="item.id">
                  <td class="record-title-cell">
                    <button class="record-title" @click="openReport(item.id)">{{ item.title }}</button>
                    <small>{{ item.report_no }} · {{ truncate(item.key_findings, 46) }}</small>
                  </td>
                  <td>{{ item.recon_links.length }} 条</td>
                  <td>{{ riskNames[item.risk_level] }}</td>
                  <td><span class="priority" :class="item.priority"><span></span>{{ priorityNames[item.priority] }}</span></td>
                  <td><StatusPill kind="report" :status="item.status" /></td>
                  <td class="date-cell">{{ formatDateTime(item.updated_at) }}</td>
                  <td class="align-right">
                    <button class="table-action" @click="openReport(item.id)">
                      {{ item.status === 'draft' ? '继续编辑 ↗' : '查看详情 ↗' }}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="pagination">
            <span>共 {{ reportsList.state.total }} 条 · 每页 {{ reportsList.state.pageSize }} 条</span>
            <div class="actions">
              <button aria-label="上一页" :disabled="reportsList.state.page <= 1" @click="reportsList.goto(reportsList.state.page - 1)">←</button>
              <span>{{ reportsList.state.page }} / {{ reportsList.pages() }}</span>
              <button aria-label="下一页" :disabled="reportsList.state.page >= reportsList.pages()" @click="reportsList.goto(reportsList.state.page + 1)">→</button>
            </div>
          </div>
        </DataState>
      </template>
    </section>

    <section class="next-step">
      <span>下一步 / NEXT STEP</span>
      <p>{{ meta.nextStep }}</p>
      <span class="next-arrow">→</span>
    </section>

    <ReconPanel :open="recordOpen" :record-id="recordId" @close="recordOpen = false" />
    <ReportPanel
      :open="reportOpen"
      :report-id="reportId"
      :seed-record-id="seedRecordId"
      @close="reportOpen = false"
      @changed="refresh"
    />
  </AppShell>
</template>
