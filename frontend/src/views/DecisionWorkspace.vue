<script setup lang="ts">
/**
 * 决策员工作台（C-06）。
 *
 * 两个视图：待研判报告（服务端指派给本人）与我的行动指令。
 * 指令下达前一定先做冲突检查，有冲突必须显式确认；总体状态只读后端重算结果。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { commandApi, reportApi } from '../api/endpoints'
import {
  priorityNames,
  reportStatusNames,
  riskNames,
  workspaceMeta,
  type AnalysisReport,
  type Command,
} from '../api/types'
import AppShell from '../components/AppShell.vue'
import DataState from '../components/DataState.vue'
import StatusPill from '../components/StatusPill.vue'
import ReportPanel from '../features/analysis/ReportPanel.vue'
import CommandPanel from '../features/decision/CommandPanel.vue'
import { usePagedList } from '../composables/usePagedList'
import { formatDateTime, truncate } from '../utils/format'

const meta = workspaceMeta.decision
const tab = ref<'reports' | 'commands'>('reports')
const commandFilter = ref('')
const counts = ref({ reports: 0, draft: 0, active: 0, completed: 0 })

const reportsList = usePagedList<AnalysisReport>(query => reportApi.list({ ...query, status: 'assigned' }))
const commandsList = usePagedList<Command>(query =>
  commandApi.list({ ...query, status: commandFilter.value || undefined }),
)

const reportOpen = ref(false)
const reportId = ref<string | null>(null)
const commandOpen = ref(false)
const commandId = ref<string | null>(null)
const seedReportId = ref<string | null>(null)

const metrics = computed(() => [
  { label: '待研判报告', value: counts.value.reports, hint: '服务端指派给本人', icon: '◷' },
  { label: '指令草稿', value: counts.value.draft, hint: '未下达，可继续修改', icon: '▤' },
  { label: '活动指令', value: counts.value.active, hint: '已下达，执行员处理中', icon: '↗' },
  { label: '已完成', value: counts.value.completed, hint: '所有执行员已反馈', icon: '✓' },
])

async function loadCounts() {
  try {
    const [reports, draft, issued, completed] = await Promise.all([
      reportApi.list({ status: 'assigned', page_size: 1 }),
      commandApi.list({ status: 'draft', page_size: 1 }),
      commandApi.list({ status: 'issued', page_size: 1 }),
      commandApi.list({ status: 'completed', page_size: 1 }),
    ])
    counts.value = {
      reports: reports.total,
      draft: draft.total,
      active: issued.total,
      completed: completed.total,
    }
  } catch {
    counts.value = { reports: 0, draft: 0, active: 0, completed: 0 }
  }
}

async function refresh() {
  await Promise.all([
    reportsList.load(reportsList.state.page, { silent: true }),
    commandsList.load(commandsList.state.page, { silent: true }),
    loadCounts(),
  ])
}

function openReport(id: string) {
  reportId.value = id
  reportOpen.value = true
}

function openCommand(id: string | null, seed: string | null = null) {
  commandId.value = id
  seedReportId.value = seed
  commandOpen.value = true
}

function issueFor(reportIdValue: string) {
  reportOpen.value = false
  openCommand(null, reportIdValue)
}

watch(commandFilter, async () => {
  commandsList.reset()
  await commandsList.load(1)
})

onMounted(refresh)
</script>

<template>
  <AppShell workspace="decision">
    <section class="page-heading">
      <div>
        <div class="eyebrow">{{ meta.stage }}</div>
        <h1>{{ meta.title }}<span class="heading-dot">.</span></h1>
        <p>{{ meta.description }}</p>
      </div>
      <button class="primary new-button" @click="openCommand(null)"><span>＋</span>{{ meta.action }}</button>
    </section>

    <section class="metric-grid" aria-label="决策概况">
      <article v-for="item in metrics" :key="item.label" :class="{ 'accent-metric': item.icon === '✓' }">
        <span>{{ item.label }}</span>
        <strong>{{ String(item.value).padStart(2, '0') }}</strong>
        <small>{{ item.hint }}</small><i>{{ item.icon }}</i>
      </article>
    </section>

    <section class="records-panel">
      <div class="panel-heading">
        <div class="tabs" role="tablist" aria-label="数据视图">
          <button role="tab" :aria-selected="tab === 'reports'" :class="{ active: tab === 'reports' }" @click="tab = 'reports'">
            待研判报告<span>{{ counts.reports }}</span>
          </button>
          <button role="tab" :aria-selected="tab === 'commands'" :class="{ active: tab === 'commands' }" @click="tab = 'commands'">
            {{ meta.listLabel }}<span>{{ commandsList.state.total }}</span>
          </button>
        </div>
        <span class="panel-caption">下达前必须完成冲突检查</span>
      </div>

      <template v-if="tab === 'reports'">
        <div class="table-toolbar">
          <div class="filters"><span class="muted">报告并列保存，不自动合并不同分析员的结论</span></div>
          <div class="actions"><button aria-label="刷新列表" @click="refresh">↻ 刷新</button></div>
        </div>
        <DataState
          :loading="reportsList.state.loading"
          :error="reportsList.state.error"
          :empty="reportsList.state.loaded && !reportsList.state.items.length"
          empty-title="没有指派给你的报告"
          empty-hint="分析员提交并指派后，报告会出现在这里。"
          @retry="refresh"
        >
          <div class="table-scroll">
            <table>
              <thead>
                <tr><th>报告 / 关键发现</th><th>引用记录</th><th>风险</th><th>优先级</th><th>状态</th><th>提交时间</th><th class="align-right">操作</th></tr>
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
                  <td class="date-cell">{{ formatDateTime(item.submitted_at) }}</td>
                  <td class="align-right">
                    <button class="table-action" @click="openReport(item.id)">查看 ↗</button>
                    <button class="table-action" @click="issueFor(item.id)">下达指令 ↗</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="pagination">
            <span>共 {{ reportsList.state.total }} 条 · {{ reportStatusNames.assigned }}</span>
            <div class="actions">
              <button aria-label="上一页" :disabled="reportsList.state.page <= 1" @click="reportsList.goto(reportsList.state.page - 1)">←</button>
              <span>{{ reportsList.state.page }} / {{ reportsList.pages() }}</span>
              <button aria-label="下一页" :disabled="reportsList.state.page >= reportsList.pages()" @click="reportsList.goto(reportsList.state.page + 1)">→</button>
            </div>
          </div>
        </DataState>
      </template>

      <template v-else>
        <div class="table-toolbar">
          <div class="filters">
            <select v-model="commandFilter" aria-label="按状态筛选指令">
              <option value="">全部状态</option>
              <option value="draft">草稿</option>
              <option value="issued">已下达待接收</option>
              <option value="accepted">已接收</option>
              <option value="executing">执行中</option>
              <option value="completed">已完成</option>
              <option value="cancelled">已取消</option>
            </select>
          </div>
          <div class="actions"><button aria-label="刷新列表" @click="refresh">↻ 刷新</button></div>
        </div>

        <DataState
          :loading="commandsList.state.loading"
          :error="commandsList.state.error"
          :empty="commandsList.state.loaded && !commandsList.state.items.length"
          empty-title="还没有指令"
          empty-hint="选择一份待研判报告后创建指令，或点击右上角新建。"
          @retry="refresh"
        >
          <div class="table-scroll">
            <table>
              <thead>
                <tr><th>指令 / 目标</th><th>优先级</th><th>执行员</th><th>状态</th><th>截止</th><th>更新时间</th><th class="align-right">操作</th></tr>
              </thead>
              <tbody>
                <tr v-for="item in commandsList.state.items" :key="item.id">
                  <td class="record-title-cell">
                    <button class="record-title" @click="openCommand(item.id)">{{ item.title }}</button>
                    <small>{{ item.command_no }} · {{ truncate(item.objective, 46) }}</small>
                  </td>
                  <td><span class="priority" :class="item.priority"><span></span>{{ priorityNames[item.priority] }}</span></td>
                  <td>{{ item.assignments.length }} 人</td>
                  <td><StatusPill kind="command" :status="item.status" /></td>
                  <td class="date-cell">{{ formatDateTime(item.deadline) }}</td>
                  <td class="date-cell">{{ formatDateTime(item.updated_at) }}</td>
                  <td class="align-right">
                    <button class="table-action" @click="openCommand(item.id)">
                      {{ item.status === 'draft' ? '继续编辑 ↗' : '查看状态 ↗' }}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="pagination">
            <span>共 {{ commandsList.state.total }} 条 · 每页 {{ commandsList.state.pageSize }} 条</span>
            <div class="actions">
              <button aria-label="上一页" :disabled="commandsList.state.page <= 1" @click="commandsList.goto(commandsList.state.page - 1)">←</button>
              <span>{{ commandsList.state.page }} / {{ commandsList.pages() }}</span>
              <button aria-label="下一页" :disabled="commandsList.state.page >= commandsList.pages()" @click="commandsList.goto(commandsList.state.page + 1)">→</button>
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

    <ReportPanel :open="reportOpen" :report-id="reportId" @close="reportOpen = false" @changed="refresh" />
    <CommandPanel
      :open="commandOpen"
      :command-id="commandId"
      :seed-report-id="seedReportId"
      @close="commandOpen = false"
      @changed="refresh"
    />
  </AppShell>
</template>
