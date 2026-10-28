<script setup lang="ts">
/**
 * 审计与调用链（需要 `audit:read`，默认由管理权限束持有）。
 *
 * 演示时最有说服力的一步：用一次提交的 `X-Request-ID` 还原跨服务调用链，
 * 看到 execution → decision → recon 各服务在同一 request_id 下的动作与结果。
 */
import { onMounted, ref } from 'vue'
import { ApiError } from '../api/client'
import { auditApi } from '../api/endpoints'
import {
  auditResultNames,
  auditResultOptions,
  workspaceMeta,
  type AuditEvent,
  type AuditTrace,
} from '../api/types'
import AppShell from '../components/AppShell.vue'
import DataState from '../components/DataState.vue'
import { usePagedList } from '../composables/usePagedList'
import { formatFull, shortId, truncate } from '../utils/format'

const meta = workspaceMeta.audit
const resultFilter = ref('')
const traceInput = ref('')
const trace = ref<AuditTrace | null>(null)
const traceError = ref<ApiError | null>(null)
const traceLoading = ref(false)

const { state, load, goto, pages, reset } = usePagedList<AuditEvent>(query =>
  auditApi.list({ ...query, result: resultFilter.value || undefined }),
  15,
)

async function refresh() {
  await load(state.page, { silent: true })
}

async function loadTrace() {
  const id = traceInput.value.trim()
  if (!id) return
  traceLoading.value = true
  traceError.value = null
  try {
    trace.value = await auditApi.trace(id)
  } catch (cause) {
    trace.value = null
    traceError.value = cause instanceof ApiError ? cause : new ApiError(0, 'NETWORK_ERROR', '调用链查询失败。')
  } finally {
    traceLoading.value = false
  }
}

function useRequestId(id: string) {
  traceInput.value = id
  void loadTrace()
}

onMounted(refresh)
</script>

<template>
  <AppShell workspace="audit">
    <section class="page-heading">
      <div>
        <div class="eyebrow">{{ meta.stage }}</div>
        <h1>{{ meta.title }}<span class="heading-dot">.</span></h1>
        <p>{{ meta.description }}</p>
      </div>
      <button class="new-button" @click="refresh">↻ {{ meta.action }}</button>
    </section>

    <section class="trace-panel">
      <div class="trace-form">
        <label for="trace-input">按请求 ID 还原调用链</label>
        <div class="form-row">
          <input
            id="trace-input"
            v-model="traceInput"
            placeholder="粘贴 X-Request-ID，例如 708a0f47-090b-462c-8026-3c601a1a910a"
            maxlength="64"
          >
          <button class="primary" :disabled="traceLoading || !traceInput.trim()" @click="loadTrace">
            {{ traceLoading ? '查询中…' : '还原调用链' }}
          </button>
        </div>
        <small class="muted">列表里每条事件的「请求 ID」都可以直接点一下填入。</small>
      </div>

      <p v-if="traceError" class="field-error" role="alert">{{ traceError.message }}</p>

      <section v-if="trace" class="trace-result">
        <header>
          <div>
            <p class="eyebrow">调用链 {{ shortId(trace.request_id) }}</p>
            <h3>{{ trace.events[0]?.action || '（无根动作）' }}</h3>
          </div>
          <span class="status-badge" :data-tone="trace.outcome === 'success' ? 'done' : 'bad'">
            {{ auditResultNames[trace.outcome] || trace.outcome }}
          </span>
        </header>
        <p class="muted">
          {{ formatFull(trace.started_at) }} → {{ formatFull(trace.completed_at) }} ·
          共 {{ trace.events.length }} 条事件
        </p>
        <ol class="timeline">
          <li v-for="event in trace.events" :key="event.id">
            <time>{{ formatFull(event.occurred_at) }}</time>
            <strong>{{ event.service }}</strong>
            <span>{{ event.action }}</span>
            <small>{{ auditResultNames[event.result] }} · {{ event.actor_role || '系统' }}</small>
          </li>
        </ol>
      </section>
    </section>

    <section class="records-panel">
      <div class="panel-heading">
        <div class="tabs" role="tablist" aria-label="数据视图">
          <button role="tab" aria-selected="true" class="active">{{ meta.listLabel }}<span>{{ state.total }}</span></button>
        </div>
        <span class="panel-caption">审计表只追加，任何角色都不能改历史</span>
      </div>

      <div class="table-toolbar">
        <div class="filters">
          <select v-model="resultFilter" aria-label="按结果筛选" @change="reset">
            <option value="">全部结果</option>
            <option v-for="option in auditResultOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </div>
        <div class="actions">
          <button aria-label="刷新列表" @click="refresh">↻ 刷新</button>
        </div>
      </div>

      <DataState
        :loading="state.loading"
        :error="state.error"
        :empty="state.loaded && !state.items.length"
        empty-title="没有审计事件"
        empty-hint="完成一次登录或业务操作后，事件会写进审计表。"
        @retry="refresh"
      >
        <div class="table-scroll">
          <table>
            <thead>
              <tr><th>时间</th><th>服务</th><th>动作</th><th>操作者</th><th>结果</th><th>请求 ID</th></tr>
            </thead>
            <tbody>
              <tr v-for="event in state.items" :key="event.id">
                <td class="date-cell">{{ formatFull(event.occurred_at) }}</td>
                <td>{{ event.service }}</td>
                <td>
                  <strong>{{ event.action }}</strong>
                  <small class="muted"> {{ truncate(String(event.resource_type || ''), 20) }}</small>
                </td>
                <td>{{ event.actor_role || '系统' }}<small class="muted"> {{ shortId(event.actor_user_id) }}</small></td>
                <td>
                  <span class="status-badge" :data-tone="event.result === 'success' ? 'done' : event.result === 'denied' ? 'bad' : 'active'">
                    {{ auditResultNames[event.result] }}
                  </span>
                </td>
                <td>
                  <button class="link-button" :title="event.request_id" @click="useRequestId(event.request_id)">
                    {{ shortId(event.request_id) }} ↗
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
  </AppShell>
</template>
