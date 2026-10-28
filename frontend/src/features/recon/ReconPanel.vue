<script setup lang="ts">
/**
 * 侦察记录面板：详情 / 编辑 / 提交 三种用法共用一份实现。
 *
 * 契约要点（services/README.md、docs/workflow.md 第 2 节）：
 * - 创建走 POST（带 Idempotency-Key），修改走 PATCH（带 expected_version）；
 * - 只有 `draft` 可以改；提交后不可直接改写；
 * - 提交时必须选择分析员，提交后状态进入 `assigned`；
 * - 证据元数据只能随创建提交（PATCH 不接受 evidence 字段）。
 */
import { computed, ref, watch } from 'vue'
import { ApiError } from '../../api/client'
import { reconApi, saveBlob } from '../../api/endpoints'
import {
  credibilityNames,
  credibilityOptions,
  priorityNames,
  priorityOptions,
  sourceTypeNames,
  sourceTypeOptions,
  type AISuggestion,
  type EvidenceInput,
  type ReconRecord,
  type ReconRecordWrite,
} from '../../api/types'
import AiSuggestionPanel from '../../components/AiSuggestionPanel.vue'
import AppDialog from '../../components/AppDialog.vue'
import CandidatePicker from '../../components/CandidatePicker.vue'
import EvidencePicker from '../../components/EvidencePicker.vue'
import StatusPill from '../../components/StatusPill.vue'
import { pushToast } from '../../stores/toast'
import { formatBytes, formatFull } from '../../utils/format'
import { newIdempotencyKey } from '../../utils/idempotency'
import { hasErrors, validateRecon, type FieldErrors } from '../../utils/validation'

const props = defineProps<{ open: boolean; recordId: string | null }>()
const emit = defineEmits<{ close: []; changed: [] }>()

const record = ref<ReconRecord | null>(null)
const suggestion = ref<AISuggestion | null>(null)
const loading = ref(false)
const saving = ref(false)
const submitting = ref(false)
const error = ref<ApiError | null>(null)
const errors = ref<FieldErrors>({})
const confirmOpen = ref(false)
const analystIds = ref<string[]>([])
const evidence = ref<EvidenceInput[]>([])

const draft = ref({
  title: '',
  source_type: 'osint' as string,
  source_ref: '',
  content: '',
  credibility: 'medium' as string,
  priority: 'normal' as string,
})

let createKey = ''
let submitKey = ''

const isNew = computed(() => !props.recordId)
const status = computed(() => record.value?.status ?? 'draft')
const editable = computed(() => isNew.value || status.value === 'draft')
const canSubmit = computed(() => editable.value && !!record.value)

function reset() {
  record.value = null
  suggestion.value = null
  evidence.value = []
  errors.value = {}
  error.value = null
  confirmOpen.value = false
  analystIds.value = []
  createKey = ''
  submitKey = ''
  draft.value = { title: '', source_type: 'osint', source_ref: '', content: '', credibility: 'medium', priority: 'normal' }
}

function fillFromRecord(value: ReconRecord) {
  draft.value = {
    title: value.title,
    source_type: value.source_type,
    source_ref: value.source_ref ?? '',
    content: value.content,
    credibility: value.credibility,
    priority: value.priority,
  }
}

async function load() {
  reset()
  if (!props.recordId) return
  loading.value = true
  try {
    const value = await reconApi.get(props.recordId)
    record.value = value
    fillFromRecord(value)
  } catch (cause) {
    error.value = cause instanceof ApiError ? cause : new ApiError(0, 'NETWORK_ERROR', '记录加载失败。')
  } finally {
    loading.value = false
  }
}

watch(() => [props.open, props.recordId], () => {
  if (props.open) void load()
})

async function saveDraft(): Promise<void> {
  errors.value = validateRecon(draft.value)
  if (hasErrors(errors.value)) return
  saving.value = true
  error.value = null
  try {
    if (!record.value) {
      createKey ||= newIdempotencyKey()
      const created = await reconApi.create(
        {
          title: draft.value.title,
          source_type: draft.value.source_type as ReconRecordWrite['source_type'],
          source_ref: draft.value.source_ref || undefined,
          content: draft.value.content,
          credibility: draft.value.credibility as ReconRecordWrite['credibility'],
          priority: draft.value.priority as ReconRecordWrite['priority'],
          evidence: evidence.value,
        },
        createKey,
      )
      record.value = created
      createKey = ''
      pushToast(`草稿已保存：${created.record_no}`, 'success')
    } else {
      const patched = await reconApi.patch(record.value.id, {
        expected_version: record.value.version,
        title: draft.value.title,
        source_type: draft.value.source_type as ReconRecordWrite['source_type'],
        source_ref: draft.value.source_ref || undefined,
        content: draft.value.content,
        credibility: draft.value.credibility as ReconRecordWrite['credibility'],
        priority: draft.value.priority as ReconRecordWrite['priority'],
      })
      record.value = patched
      pushToast('草稿已更新', 'success')
    }
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

function askSubmit() {
  errors.value = validateRecon(draft.value)
  if (hasErrors(errors.value)) return
  confirmOpen.value = true
}

async function submitRecord() {
  if (!record.value || !analystIds.value.length) {
    pushToast('请至少选择一名分析员。', 'error')
    return
  }
  submitting.value = true
  error.value = null
  try {
    submitKey ||= newIdempotencyKey()
    const submitted = await reconApi.submit(
      record.value.id,
      { expected_version: record.value.version, analyst_ids: analystIds.value },
      submitKey,
    )
    record.value = submitted
    submitKey = ''
    confirmOpen.value = false
    pushToast('侦察记录已提交并指派分析员', 'success')
    emit('changed')
  } catch (cause) {
    const apiError = cause instanceof ApiError ? cause : new ApiError(0, 'NETWORK_ERROR', '提交失败。')
    error.value = apiError
    pushToast(apiError.message, 'error', apiError.conflict)
  } finally {
    submitting.value = false
  }
}

async function downloadEvidence(evidenceId: string, fileName: string) {
  if (!record.value) return
  try {
    const blob = await reconApi.downloadEvidence(record.value.id, evidenceId)
    saveBlob(blob, fileName)
  } catch (cause) {
    const apiError = cause instanceof ApiError ? cause : new ApiError(0, 'NETWORK_ERROR', '下载失败。')
    pushToast(
      apiError.notFound
        ? '证据文件不在服务端受控目录：当前契约没有上传端点，只有元数据。'
        : apiError.message,
      'error',
    )
  }
}

function close() {
  if (saving.value || submitting.value) return
  emit('close')
}
</script>

<template>
  <AppDialog
    :open="open"
    :busy="saving || submitting"
    wide
    :eyebrow="isNew ? '01 / OBSERVE · 新建' : `记录 ${record?.record_no ?? ''}`"
    :title="isNew ? '新建侦察记录' : record?.title || '侦察记录'"
    @close="close"
  >
    <p v-if="loading" class="muted" role="status"><span class="spinner" aria-hidden="true"></span> 正在加载记录…</p>
    <p v-else-if="error && !record" class="field-error" role="alert">{{ error.message }}</p>

    <template v-else>
      <div v-if="record" class="panel-meta">
        <StatusPill kind="recon" :status="record.status" />
        <span class="muted">可信度：{{ credibilityNames[record.credibility] }} · 优先级：{{ priorityNames[record.priority] }}</span>
        <span class="muted">更新时间：{{ formatFull(record.updated_at) }} · 版本 v{{ record.version }}</span>
      </div>

      <template v-if="editable">
        <div class="form-field">
          <label for="recon-title">标题 <span aria-hidden="true">*</span></label>
          <input id="recon-title" v-model="draft.title" maxlength="200" :aria-invalid="!!errors.title" aria-describedby="recon-title-error" placeholder="一句话说清这条信息在讲什么">
          <small id="recon-title-error" class="field-error">{{ errors.title }}</small>
        </div>
        <div class="form-row">
          <div class="form-field">
            <label for="recon-source-type">来源类型 <span aria-hidden="true">*</span></label>
            <select id="recon-source-type" v-model="draft.source_type">
              <option v-for="option in sourceTypeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
            <small class="field-error">{{ errors.source_type }}</small>
          </div>
          <div class="form-field">
            <label for="recon-credibility">可信度 <span aria-hidden="true">*</span></label>
            <select id="recon-credibility" v-model="draft.credibility">
              <option v-for="option in credibilityOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
            <small class="field-error">{{ errors.credibility }}</small>
          </div>
          <div class="form-field">
            <label for="recon-priority">优先级 <span aria-hidden="true">*</span></label>
            <select id="recon-priority" v-model="draft.priority">
              <option v-for="option in priorityOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
            <small class="field-error">{{ errors.priority }}</small>
          </div>
        </div>
        <div class="form-field">
          <label for="recon-source-ref">来源说明</label>
          <input id="recon-source-ref" v-model="draft.source_ref" maxlength="500" placeholder="脱敏后的来源，例如「公开报道整理」">
          <small class="field-error">{{ errors.source_ref }}</small>
        </div>
        <div class="form-field">
          <label for="recon-content">正文 <span aria-hidden="true">*</span></label>
          <textarea id="recon-content" v-model="draft.content" rows="7" maxlength="8000" :aria-invalid="!!errors.content" aria-describedby="recon-content-error" placeholder="写清观察时间、地点、事实与不确定的地方。"></textarea>
          <div class="input-meta">
            <small id="recon-content-error" class="field-error">{{ errors.content }}</small>
            <small>{{ draft.content.length }} / 8000</small>
          </div>
        </div>

        <EvidencePicker v-if="!record" v-model="evidence" :disabled="saving" />
        <p v-else class="notice compact">证据元数据只能随创建提交；当前契约的 PATCH 不接受新证据。</p>

        <AiSuggestionPanel
          v-model:suggestion="suggestion"
          stage="recon"
          object-type="recon_record"
          :object-id="record?.id ?? ''"
          suggestion-type="summary"
          :disabled="!record"
        />
      </template>

      <template v-else>
        <dl class="kv-grid">
          <div><dt>来源类型</dt><dd>{{ sourceTypeNames[record?.source_type ?? 'other'] }}</dd></div>
          <div><dt>来源说明</dt><dd>{{ record?.source_ref || '未填写' }}</dd></div>
          <div><dt>可信度</dt><dd>{{ credibilityNames[record?.credibility ?? 'unverified'] }}</dd></div>
          <div><dt>优先级</dt><dd>{{ priorityNames[record?.priority ?? 'normal'] }}</dd></div>
          <div><dt>提交时间</dt><dd>{{ formatFull(record?.submitted_at) }}</dd></div>
        </dl>
        <section class="detail-section">
          <p class="eyebrow">正文</p>
          <p class="record-content">{{ record?.content }}</p>
        </section>
        <section class="detail-section">
          <p class="eyebrow">证据（{{ record?.evidence?.length ?? 0 }}）</p>
          <ul v-if="record?.evidence?.length" class="evidence-list">
            <li v-for="item in record.evidence" :key="item.id">
              <span>
                <strong>{{ item.file_name }}</strong>
                <small>{{ item.media_type }} · {{ formatBytes(item.size_bytes) }} · sha256 {{ item.sha256.slice(0, 12) }}…</small>
              </span>
              <button type="button" @click="downloadEvidence(item.id, item.file_name)">下载</button>
            </li>
          </ul>
          <p v-else class="muted">这条记录没有关联证据。</p>
        </section>
        <section class="detail-section">
          <p class="eyebrow">分析员指派</p>
          <ul v-if="record?.assignments?.length" class="evidence-list">
            <li v-for="item in record.assignments" :key="item.id">
              <span>
                <strong>{{ item.analyst_id.slice(0, 8) }}</strong>
                <small>{{ item.status }} · 指派于 {{ formatFull(item.assigned_at) }}</small>
              </span>
            </li>
          </ul>
          <p v-else class="muted">尚未指派分析员。</p>
        </section>
      </template>

      <div v-if="confirmOpen" class="confirm-panel" role="alert">
        <span class="eyebrow">提交确认</span>
        <h3>{{ draft.title }}</h3>
        <CandidatePicker v-model="analystIds" target-role="analyst" role-label="指派分析员" :disabled="submitting" />
        <p class="muted">提交后记录进入「已指派待分析」，你不能再直接改写内容。</p>
      </div>

      <p v-if="error?.requestId" class="muted">请求 ID：{{ error.requestId }}</p>
    </template>

    <template #footer>
      <div class="actions footer-split">
        <span class="muted">* 为提交必填项；保存草稿会写入真实后端。</span>
        <div class="actions">
          <button v-if="editable" type="button" :disabled="saving || submitting" @click="saveDraft">
            {{ saving ? '正在保存…' : record ? '保存修改' : '保存草稿' }}
          </button>
          <button v-if="confirmOpen" type="button" :disabled="submitting" @click="confirmOpen = false">返回修改</button>
          <button v-if="canSubmit && !confirmOpen" type="button" class="primary" :disabled="saving" @click="askSubmit">
            提交给分析员 →
          </button>
          <button v-if="confirmOpen" type="button" class="primary" :disabled="submitting || !analystIds.length" @click="submitRecord">
            {{ submitting ? '正在提交…' : '确认提交' }}
          </button>
        </div>
      </div>
    </template>
  </AppDialog>
</template>
