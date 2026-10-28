<script setup lang="ts">
/**
 * 执行分配面板：接收 → 开始 → 提交结果。
 *
 * 契约要点（services/README.md、docs/workflow.md 第 5 节）：
 * - 执行员只能读自己的分配，他人分配服务端按 404 处理；
 * - 每次状态转换都要带 `expected_version`，旧版本返回 409；
 * - 结果提交是幂等操作，重复提交返回原结果或 409，不会生成第二份。
 */
import { computed, ref, watch } from 'vue'
import { ApiError } from '../../api/client'
import { assignmentApi, saveBlob } from '../../api/endpoints'
import {
  assignmentStatusNames,
  outcomeNames,
  outcomeOptions,
  priorityNames,
  type Assignment,
  type EvidenceInput,
} from '../../api/types'
import AppDialog from '../../components/AppDialog.vue'
import EvidencePicker from '../../components/EvidencePicker.vue'
import StatusPill from '../../components/StatusPill.vue'
import { pushToast } from '../../stores/toast'
import { formatBytes, formatFull } from '../../utils/format'
import { newIdempotencyKey } from '../../utils/idempotency'
import { hasErrors, validateResult, type FieldErrors } from '../../utils/validation'

const props = defineProps<{ open: boolean; assignmentId: string | null }>()
const emit = defineEmits<{ close: []; changed: [] }>()

const assignment = ref<Assignment | null>(null)
const loading = ref(false)
const busy = ref(false)
const error = ref<ApiError | null>(null)
const errors = ref<FieldErrors>({})
const mode = ref<'view' | 'complete' | 'reject'>('view')
const resultDraft = ref({ outcome: 'success', summary: '', detail: '' })
const evidence = ref<EvidenceInput[]>([])
const rejectReason = ref('')
let completeKey = ''

const status = computed(() => assignment.value?.status ?? 'pending')
const canAccept = computed(() => status.value === 'pending')
const canStart = computed(() => status.value === 'accepted')
const canComplete = computed(() => status.value === 'accepted' || status.value === 'executing')
const canReject = computed(() => status.value === 'pending' || status.value === 'accepted')

async function load() {
  assignment.value = null
  error.value = null
  mode.value = 'view'
  errors.value = {}
  evidence.value = []
  resultDraft.value = { outcome: 'success', summary: '', detail: '' }
  rejectReason.value = ''
  completeKey = ''
  if (!props.assignmentId) return
  loading.value = true
  try {
    assignment.value = await assignmentApi.get(props.assignmentId)
  } catch (cause) {
    error.value = cause instanceof ApiError ? cause : new ApiError(0, 'NETWORK_ERROR', '执行任务加载失败。')
  } finally {
    loading.value = false
  }
}

watch(() => [props.open, props.assignmentId], () => {
  if (props.open) void load()
})

async function transition(action: 'accept' | 'start') {
  if (!assignment.value) return
  busy.value = true
  error.value = null
  try {
    assignment.value =
      action === 'accept'
        ? await assignmentApi.accept(assignment.value.id, { expected_version: assignment.value.version })
        : await assignmentApi.start(assignment.value.id, { expected_version: assignment.value.version })
    pushToast(action === 'accept' ? '已接收指令' : '已标记开始执行', 'success')
    emit('changed')
  } catch (cause) {
    const apiError = cause instanceof ApiError ? cause : new ApiError(0, 'NETWORK_ERROR', '操作失败。')
    error.value = apiError
    pushToast(apiError.message, 'error', apiError.conflict)
  } finally {
    busy.value = false
  }
}

async function reject() {
  if (!assignment.value) return
  if (rejectReason.value.trim().length < 2) {
    pushToast('拒绝指令必须填写理由（至少 2 个字）。', 'error')
    return
  }
  busy.value = true
  try {
    assignment.value = await assignmentApi.reject(assignment.value.id, {
      expected_version: assignment.value.version,
      reason: rejectReason.value.trim(),
    })
    mode.value = 'view'
    pushToast('已拒绝该指令', 'success')
    emit('changed')
  } catch (cause) {
    const apiError = cause instanceof ApiError ? cause : new ApiError(0, 'NETWORK_ERROR', '操作失败。')
    pushToast(apiError.message, 'error')
  } finally {
    busy.value = false
  }
}

async function complete() {
  if (!assignment.value) return
  errors.value = validateResult(resultDraft.value)
  if (hasErrors(errors.value)) return
  busy.value = true
  error.value = null
  try {
    completeKey ||= newIdempotencyKey()
    assignment.value = await assignmentApi.complete(
      assignment.value.id,
      {
        expected_version: assignment.value.version,
        outcome: resultDraft.value.outcome as 'success' | 'partial' | 'failure',
        summary: resultDraft.value.summary,
        detail: resultDraft.value.detail || undefined,
        evidence: evidence.value,
      },
      completeKey,
    )
    completeKey = ''
    mode.value = 'view'
    pushToast('执行结果已提交', 'success')
    emit('changed')
  } catch (cause) {
    const apiError = cause instanceof ApiError ? cause : new ApiError(0, 'NETWORK_ERROR', '提交失败。')
    error.value = apiError
    errors.value = Object.fromEntries(apiError.issues.map(issue => [issue.field, issue.message]))
    pushToast(apiError.message, 'error', apiError.conflict)
  } finally {
    busy.value = false
  }
}

async function downloadEvidence(evidenceId: string, fileName: string) {
  if (!assignment.value) return
  try {
    saveBlob(await assignmentApi.downloadEvidence(assignment.value.id, evidenceId), fileName)
  } catch (cause) {
    const apiError = cause instanceof ApiError ? cause : new ApiError(0, 'NETWORK_ERROR', '下载失败。')
    pushToast(
      apiError.notFound ? '证据文件不在服务端受控目录：当前契约没有上传端点，只有元数据。' : apiError.message,
      'error',
    )
  }
}
</script>

<template>
  <AppDialog
    :open="open"
    :busy="busy"
    wide
    eyebrow="04 / ACT · 执行任务"
    :title="assignment?.command_title_snapshot || '执行任务'"
    @close="emit('close')"
  >
    <p v-if="loading" class="muted" role="status"><span class="spinner" aria-hidden="true"></span> 正在加载执行任务…</p>
    <p v-else-if="error && !assignment" class="field-error" role="alert">{{ error.message }}</p>

    <template v-else-if="assignment">
      <div class="panel-meta">
        <StatusPill kind="assignment" :status="assignment.status" />
        <span class="muted">优先级：{{ priorityNames[assignment.priority] }}</span>
        <span class="muted">截止：{{ formatFull(assignment.deadline) }}</span>
        <span class="muted">版本 v{{ assignment.version }}</span>
      </div>

      <section class="detail-section">
        <p class="eyebrow">指令内容（下达时快照）</p>
        <p class="record-content">{{ assignment.command_content_snapshot }}</p>
      </section>

      <dl class="kv-grid">
        <div><dt>接收时间</dt><dd>{{ formatFull(assignment.accepted_at) }}</dd></div>
        <div><dt>开始时间</dt><dd>{{ formatFull(assignment.started_at) }}</dd></div>
        <div><dt>完成时间</dt><dd>{{ formatFull(assignment.completed_at) }}</dd></div>
        <div><dt>拒绝原因</dt><dd>{{ assignment.reject_reason || '—' }}</dd></div>
      </dl>

      <section v-if="assignment.result" class="detail-section">
        <p class="eyebrow">执行结果</p>
        <dl class="kv-grid">
          <div><dt>结论</dt><dd>{{ outcomeNames[assignment.result.outcome] || assignment.result.outcome }}</dd></div>
          <div><dt>上报时间</dt><dd>{{ formatFull(assignment.result.reported_at) }}</dd></div>
        </dl>
        <p class="record-content">{{ assignment.result.summary }}</p>
        <p v-if="assignment.result.detail" class="muted">{{ assignment.result.detail }}</p>
        <ul v-if="assignment.result.evidence?.length" class="evidence-list">
          <li v-for="item in assignment.result.evidence" :key="item.id">
            <span>
              <strong>{{ item.file_name }}</strong>
              <small>{{ item.media_type }} · {{ formatBytes(item.size_bytes) }} · sha256 {{ item.sha256.slice(0, 12) }}…</small>
            </span>
            <button type="button" @click="downloadEvidence(item.id, item.file_name)">下载</button>
          </li>
        </ul>
      </section>

      <template v-if="mode === 'complete'">
        <div class="confirm-panel">
          <span class="eyebrow">提交执行结果</span>
          <div class="form-field">
            <label for="result-outcome">结论 <span aria-hidden="true">*</span></label>
            <select id="result-outcome" v-model="resultDraft.outcome">
              <option v-for="option in outcomeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
            <small class="field-error">{{ errors.outcome }}</small>
          </div>
          <div class="form-field">
            <label for="result-summary">结果摘要 <span aria-hidden="true">*</span></label>
            <input id="result-summary" v-model="resultDraft.summary" maxlength="2000" :aria-invalid="!!errors.summary" placeholder="一句话说明执行到了什么程度">
            <small class="field-error">{{ errors.summary }}</small>
          </div>
          <div class="form-field">
            <label for="result-detail">过程与异常</label>
            <textarea id="result-detail" v-model="resultDraft.detail" rows="4" maxlength="8000" placeholder="执行过程、异常接触、证据位置等。"></textarea>
            <small class="field-error">{{ errors.detail }}</small>
          </div>
          <EvidencePicker v-model="evidence" :disabled="busy" />
          <p class="muted">提交后这条分配进入完成/失败状态，不能重复提交第二份结果。</p>
        </div>
      </template>

      <template v-if="mode === 'reject'">
        <div class="confirm-panel">
          <span class="eyebrow">拒绝指令</span>
          <div class="form-field">
            <label for="reject-reason">拒绝理由 <span aria-hidden="true">*</span></label>
            <input id="reject-reason" v-model="rejectReason" maxlength="500" placeholder="写清为什么不能执行（至少 2 个字）">
          </div>
          <p class="muted">拒绝会记录到审计，决策员能看到理由。</p>
        </div>
      </template>

      <p v-if="error?.requestId" class="muted">请求 ID：{{ error.requestId }}</p>
    </template>

    <template #footer>
      <div class="actions footer-split">
        <span class="muted">{{ assignmentStatusNames[status] }}</span>
        <div class="actions">
          <template v-if="mode !== 'view'">
            <button type="button" :disabled="busy" @click="mode = 'view'">返回</button>
            <button v-if="mode === 'reject'" type="button" class="danger-button" :disabled="busy" @click="reject">确认拒绝</button>
            <button v-if="mode === 'complete'" type="button" class="primary" :disabled="busy" @click="complete">
              {{ busy ? '正在提交…' : '提交结果' }}
            </button>
          </template>
          <template v-else>
            <button v-if="canReject" type="button" :disabled="busy" @click="mode = 'reject'">拒绝</button>
            <button v-if="canAccept" type="button" class="primary" :disabled="busy" @click="transition('accept')">接收指令</button>
            <button v-if="canStart" type="button" class="primary" :disabled="busy" @click="transition('start')">开始执行</button>
            <button v-if="canComplete" type="button" class="primary" :disabled="busy" @click="mode = 'complete'">填写结果并提交</button>
          </template>
        </div>
      </div>
    </template>
  </AppDialog>
</template>
