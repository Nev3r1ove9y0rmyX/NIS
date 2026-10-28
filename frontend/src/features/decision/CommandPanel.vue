<script setup lang="ts">
/**
 * 决策指令面板：依据被指派的报告起草指令 → 冲突检查 → 二次确认 → 下达。
 *
 * 契约要点（services/README.md、docs/workflow.md 第 4 节）：
 * - 依据报告必须是「已指派给本人」的报告；
 * - 下达前必须做过冲突检查；有冲突时 `conflict_acknowledged=true` 才能下达；
 * - 指令下达后核心内容不可改写，变更要取消旧指令再新建；
 * - 总体状态只由 Decision 服务重算，前端只读取 `GET /commands/{id}/status`。
 */
import { computed, ref, watch } from 'vue'
import { ApiError } from '../../api/client'
import { commandApi, reportApi } from '../../api/endpoints'
import {
  assignmentStatusNames,
  commandStatusNames,
  outcomeNames,
  priorityNames,
  priorityOptions,
  reportStatusNames,
  riskNames,
  type AISuggestion,
  type AnalysisReport,
  type Command,
  type CommandStatusView,
  type ConflictCheckResult,
} from '../../api/types'
import AiSuggestionPanel from '../../components/AiSuggestionPanel.vue'
import AppDialog from '../../components/AppDialog.vue'
import CandidatePicker from '../../components/CandidatePicker.vue'
import StatusPill from '../../components/StatusPill.vue'
import { pushToast } from '../../stores/toast'
import { formatFull, isoToLocalInput, localInputToIso, truncate } from '../../utils/format'
import { newIdempotencyKey } from '../../utils/idempotency'
import { hasErrors, validateCommand, type FieldErrors } from '../../utils/validation'
import type { CommandResultItem } from '../../api/endpoints'

const props = defineProps<{ open: boolean; commandId: string | null; seedReportId?: string | null }>()
const emit = defineEmits<{ close: []; changed: [] }>()

const command = ref<Command | null>(null)
const statusView = ref<CommandStatusView | null>(null)
const results = ref<CommandResultItem[]>([])
const suggestion = ref<AISuggestion | null>(null)
const reports = ref<AnalysisReport[]>([])
const loading = ref(false)
const saving = ref(false)
const issuing = ref(false)
const cancelling = ref(false)
const error = ref<ApiError | null>(null)
const errors = ref<FieldErrors>({})
const issueOpen = ref(false)
const conflicts = ref<ConflictCheckResult | null>(null)
const acknowledged = ref(false)
const executorIds = ref<string[]>([])
const cancelReason = ref('')

const draft = ref({
  title: '',
  objective: '',
  content: '',
  priority: 'normal' as string,
  deadline: '',
  source_report_id: '',
})

let createKey = ''
let issueKey = ''

const isNew = computed(() => !props.commandId)
const editable = computed(() => isNew.value || command.value?.status === 'draft')
const canIssue = computed(() => editable.value && !!command.value)
const activeStatus = computed(() => command.value?.status ?? 'draft')
const canCancel = computed(() =>
  ['issued', 'partially_accepted', 'accepted', 'executing'].includes(activeStatus.value),
)

function reset() {
  command.value = null
  statusView.value = null
  results.value = []
  suggestion.value = null
  errors.value = {}
  error.value = null
  issueOpen.value = false
  conflicts.value = null
  acknowledged.value = false
  executorIds.value = []
  cancelReason.value = ''
  createKey = ''
  issueKey = ''
  draft.value = {
    title: '',
    objective: '',
    content: '',
    priority: 'normal',
    deadline: '',
    source_report_id: props.seedReportId ?? '',
  }
}

async function load() {
  reset()
  loading.value = true
  try {
    const page = await reportApi.list({ status: 'assigned', page_size: 50 })
    reports.value = page.items
    if (props.commandId) {
      const value = await commandApi.get(props.commandId)
      command.value = value
      draft.value = {
        title: value.title,
        objective: value.objective,
        content: value.content,
        priority: value.priority,
        deadline: isoToLocalInput(value.deadline),
        source_report_id: value.source_report_id,
      }
      await refreshStatus()
    }
  } catch (cause) {
    error.value = cause instanceof ApiError ? cause : new ApiError(0, 'NETWORK_ERROR', '指令加载失败。')
  } finally {
    loading.value = false
  }
}

async function refreshStatus() {
  if (!command.value) return
  try {
    statusView.value = await commandApi.status(command.value.id)
  } catch (cause) {
    // 草稿阶段的总体状态接口可能还没有分配可读，不把这类 404 当失败展示。
    statusView.value = null
    if (cause instanceof ApiError && !cause.notFound) error.value = cause
  }
  if (command.value.status === 'draft') {
    results.value = []
    return
  }
  try {
    results.value = (await commandApi.results(command.value.id)).items
  } catch {
    // 尚无执行结果时结果接口返回 404，属正常状态，不当错误提示。
    results.value = []
  }
}

watch(() => [props.open, props.commandId], () => {
  if (props.open) void load()
})

async function saveDraft(): Promise<void> {
  errors.value = validateCommand(draft.value)
  if (hasErrors(errors.value)) return
  saving.value = true
  error.value = null
  try {
    const deadline = localInputToIso(draft.value.deadline)
    if (!command.value) {
      createKey ||= newIdempotencyKey()
      command.value = await commandApi.create(
        {
          title: draft.value.title,
          objective: draft.value.objective,
          content: draft.value.content,
          priority: draft.value.priority as Command['priority'],
          deadline: deadline ?? undefined,
          source_report_id: draft.value.source_report_id,
        },
        createKey,
      )
      createKey = ''
      pushToast(`指令草稿已保存：${command.value.command_no}`, 'success')
    } else {
      command.value = await commandApi.patch(command.value.id, {
        expected_version: command.value.version,
        title: draft.value.title,
        objective: draft.value.objective,
        content: draft.value.content,
        priority: draft.value.priority as Command['priority'],
        deadline: deadline ?? undefined,
      })
      pushToast('指令草稿已更新', 'success')
    }
    await refreshStatus()
    emit('changed')
  } catch (cause) {
    const apiError = cause instanceof ApiError ? cause : new ApiError(0, 'NETWORK_ERROR', '保存失败。')
    error.value = apiError
    errors.value = Object.fromEntries(apiError.issues.map(issue => [issue.field, issue.message]))
    pushToast(apiError.message, 'error', apiError.conflict)
  } finally {
    saving.value = false
  }
}

async function prepareIssue() {
  errors.value = validateCommand(draft.value)
  if (hasErrors(errors.value)) return
  if (!command.value) {
    pushToast('先保存草稿，再做冲突检查。', 'error')
    return
  }
  error.value = null
  issueOpen.value = true
  conflicts.value = null
  acknowledged.value = false
  try {
    conflicts.value = await commandApi.conflicts(
      draft.value.source_report_id,
      draft.value.objective,
      command.value.id,
    )
  } catch (cause) {
    const apiError = cause instanceof ApiError ? cause : new ApiError(0, 'NETWORK_ERROR', '冲突检查失败。')
    error.value = apiError
    pushToast(apiError.message, 'error')
  }
}

async function issue() {
  if (!command.value || !executorIds.value.length) {
    pushToast('请至少选择一名执行员。', 'error')
    return
  }
  if (conflicts.value?.has_conflict && !acknowledged.value) {
    pushToast('存在潜在冲突时，必须明确勾选「知悉冲突并继续」。', 'error')
    return
  }
  issuing.value = true
  error.value = null
  try {
    issueKey ||= newIdempotencyKey()
    command.value = await commandApi.issue(
      command.value.id,
      {
        expected_version: command.value.version,
        executor_ids: executorIds.value,
        conflict_acknowledged: acknowledged.value,
      },
      issueKey,
    )
    issueKey = ''
    issueOpen.value = false
    await refreshStatus()
    pushToast('指令已下达给执行员', 'success')
    emit('changed')
  } catch (cause) {
    const apiError = cause instanceof ApiError ? cause : new ApiError(0, 'NETWORK_ERROR', '下达失败。')
    error.value = apiError
    pushToast(apiError.message, 'error', true)
  } finally {
    issuing.value = false
  }
}

async function cancel() {
  if (!command.value || cancelReason.value.trim().length < 2) {
    pushToast('取消指令必须填写理由（至少 2 个字）。', 'error')
    return
  }
  cancelling.value = true
  try {
    command.value = await commandApi.cancel(command.value.id, {
      expected_version: command.value.version,
      reason: cancelReason.value.trim(),
    })
    cancelReason.value = ''
    await refreshStatus()
    pushToast('指令已取消', 'success')
    emit('changed')
  } catch (cause) {
    const apiError = cause instanceof ApiError ? cause : new ApiError(0, 'NETWORK_ERROR', '取消失败。')
    pushToast(apiError.message, 'error')
  } finally {
    cancelling.value = false
  }
}
</script>

<template>
  <AppDialog
    :open="open"
    :busy="saving || issuing"
    wide
    :eyebrow="isNew ? '03 / DECIDE · 新建' : `指令 ${command?.command_no ?? ''}`"
    :title="isNew ? '创建行动指令' : command?.title || '行动指令'"
    @close="emit('close')"
  >
    <p v-if="loading" class="muted" role="status"><span class="spinner" aria-hidden="true"></span> 正在加载报告与指令…</p>
    <p v-else-if="error && !command" class="field-error" role="alert">{{ error.message }}</p>

    <template v-else>
      <div v-if="command" class="panel-meta">
        <StatusPill kind="command" :status="command.status" />
        <span class="muted">优先级：{{ priorityNames[command.priority] }}</span>
        <span class="muted">下达时间：{{ formatFull(command.issued_at) }}</span>
        <span class="muted">版本 v{{ command.version }}</span>
      </div>

      <template v-if="editable">
        <div class="form-field">
          <label for="command-title">标题 <span aria-hidden="true">*</span></label>
          <input id="command-title" v-model="draft.title" maxlength="200" :aria-invalid="!!errors.title" placeholder="例如：固定时段观察任务">
          <small class="field-error">{{ errors.title }}</small>
        </div>
        <div class="form-field">
          <label for="command-objective">目标 <span aria-hidden="true">*</span></label>
          <input id="command-objective" v-model="draft.objective" maxlength="500" :aria-invalid="!!errors.objective" placeholder="这次行动要达成什么">
          <small class="field-error">{{ errors.objective }}</small>
        </div>
        <div class="form-field">
          <label for="command-content">行动内容 <span aria-hidden="true">*</span></label>
          <textarea id="command-content" v-model="draft.content" rows="5" maxlength="8000" :aria-invalid="!!errors.content" placeholder="做什么、谁来做、边界在哪里。"></textarea>
          <div class="input-meta">
            <small class="field-error">{{ errors.content }}</small>
            <small>{{ draft.content.length }} / 8000</small>
          </div>
        </div>
        <div class="form-row">
          <div class="form-field">
            <label for="command-priority">优先级 <span aria-hidden="true">*</span></label>
            <select id="command-priority" v-model="draft.priority">
              <option v-for="option in priorityOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
            <small class="field-error">{{ errors.priority }}</small>
          </div>
          <div class="form-field">
            <label for="command-deadline">截止时间</label>
            <input id="command-deadline" v-model="draft.deadline" type="datetime-local" :aria-invalid="!!errors.deadline">
            <small class="field-error">{{ errors.deadline }}</small>
          </div>
        </div>
        <div class="form-field">
          <label for="command-source">依据报告 <span aria-hidden="true">*</span></label>
          <select id="command-source" v-model="draft.source_report_id" :disabled="!!command">
            <option value="">请选择一份已指派给你的报告</option>
            <option v-for="item in reports" :key="item.id" :value="item.id">
              {{ item.report_no }} · {{ truncate(item.title, 34) }} · {{ reportStatusNames[item.status] }} · 风险 {{ riskNames[item.risk_level] }}
            </option>
          </select>
          <small class="field-error">{{ errors.source_report_id }}</small>
          <small v-if="!reports.length" class="muted">目前没有被指派给你的报告，等分析员提交后再下达指令。</small>
        </div>

        <AiSuggestionPanel
          v-model:suggestion="suggestion"
          stage="decision"
          object-type="command"
          :object-id="command?.id ?? ''"
          suggestion-type="action_options"
          :disabled="!command"
        />
      </template>

      <template v-else>
        <dl class="kv-grid">
          <div><dt>目标</dt><dd>{{ command?.objective }}</dd></div>
          <div><dt>优先级</dt><dd>{{ priorityNames[command?.priority ?? 'normal'] }}</dd></div>
          <div><dt>截止时间</dt><dd>{{ formatFull(command?.deadline) }}</dd></div>
          <div><dt>下达时间</dt><dd>{{ formatFull(command?.issued_at) }}</dd></div>
          <div><dt>取消原因</dt><dd>{{ command?.cancel_reason || '—' }}</dd></div>
        </dl>
        <section class="detail-section">
          <p class="eyebrow">行动内容</p>
          <p class="record-content">{{ command?.content }}</p>
        </section>
        <section class="detail-section">
          <p class="eyebrow">执行分配与状态（总体状态由后端重算）</p>
          <ul v-if="statusView?.assignments?.length" class="evidence-list">
            <li v-for="item in statusView.assignments" :key="item.assignment_id || item.executor_id">
              <span>
                <strong>{{ item.executor_id.slice(0, 8) }}</strong>
                <small>{{ assignmentStatusNames[item.status] || item.status }}
                  <template v-if="item.accepted_at"> · 接收 {{ formatFull(item.accepted_at) }}</template>
                  <template v-if="item.completed_at"> · 完成 {{ formatFull(item.completed_at) }}</template>
                </small>
              </span>
            </li>
          </ul>
          <p v-else class="muted">还没有执行分配。</p>
        </section>
        <section class="detail-section">
          <p class="eyebrow">执行结果</p>
          <ul v-if="results.length" class="evidence-list">
            <li v-for="item in results" :key="item.assignment_id">
              <span>
                <strong>{{ item.executor_id.slice(0, 8) }}</strong>
                <small>{{ assignmentStatusNames[item.status] || item.status }}
                  <template v-if="item.outcome"> · 结论 {{ outcomeNames[item.outcome as keyof typeof outcomeNames] || item.outcome }}</template>
                  <template v-if="item.completed_at"> · {{ formatFull(item.completed_at) }}</template>
                </small>
              </span>
            </li>
          </ul>
          <p v-else class="muted">执行员还没有提交结果。</p>
        </section>

        <section v-if="canCancel" class="detail-section">
          <p class="eyebrow">取消指令（保留审计，不删除记录）</p>
          <div class="form-row cancel-row">
            <input v-model="cancelReason" maxlength="500" placeholder="填写取消理由（至少 2 个字）">
            <button type="button" class="danger-button" :disabled="cancelling" @click="cancel">
              {{ cancelling ? '正在取消…' : '取消指令' }}
            </button>
          </div>
        </section>
      </template>

      <div v-if="issueOpen" class="confirm-panel" role="alert">
        <span class="eyebrow">下达确认</span>
        <h3>{{ draft.title }}</h3>
        <p class="muted">
          报告：{{ truncate(reports.find(item => item.id === draft.source_report_id)?.title || draft.source_report_id, 40) }}
          · 优先级 {{ priorityNames[draft.priority as keyof typeof priorityNames] }}
          · 截止 {{ draft.deadline || '未设置' }}
        </p>

        <div class="conflict-box" :data-has-conflict="conflicts?.has_conflict ? 'true' : 'false'">
          <p v-if="!conflicts" class="muted">正在做冲突检查…</p>
          <template v-else-if="!conflicts.has_conflict">
            <strong>没有发现冲突</strong>
            <p class="muted">同一报告与同一目标下没有活动指令。</p>
          </template>
          <template v-else>
            <strong>发现 {{ conflicts.conflicts.length }} 条潜在冲突</strong>
            <ul>
              <li v-for="item in conflicts.conflicts" :key="item.command_id">
                {{ item.command_no }} · {{ commandStatusNames[item.status as keyof typeof commandStatusNames] || item.status }} · {{ item.reason || '同一目标已有活动指令' }}
              </li>
            </ul>
            <label class="check-label">
              <input v-model="acknowledged" type="checkbox">
              我已核对上述活动指令，知悉冲突并继续下达（会写入高重要度审计）。
            </label>
          </template>
        </div>

        <CandidatePicker v-model="executorIds" target-role="executor" role-label="指定执行员" :disabled="issuing" />
        <p class="muted">下达后核心内容不可改写；需要变更时取消旧指令并新建。</p>
      </div>

      <p v-if="error?.requestId" class="muted">请求 ID：{{ error.requestId }}</p>
    </template>

    <template #footer>
      <div class="actions footer-split">
        <span class="muted">* 为提交必填项</span>
        <div class="actions">
          <button v-if="editable" type="button" :disabled="saving || issuing" @click="saveDraft">
            {{ saving ? '正在保存…' : command ? '保存修改' : '保存草稿' }}
          </button>
          <button v-if="issueOpen" type="button" :disabled="issuing" @click="issueOpen = false">返回修改</button>
          <button v-if="canIssue && !issueOpen" type="button" class="primary" :disabled="saving" @click="prepareIssue">
            冲突检查并下达 →
          </button>
          <button
            v-if="issueOpen"
            type="button"
            class="primary"
            :disabled="issuing || !executorIds.length || (conflicts?.has_conflict === true && !acknowledged)"
            @click="issue"
          >
            {{ issuing ? '正在下达…' : '确认下达' }}
          </button>
        </div>
      </div>
    </template>
  </AppDialog>
</template>
