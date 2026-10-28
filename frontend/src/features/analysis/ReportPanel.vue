<script setup lang="ts">
/**
 * 分析报告面板：读取被指派的侦察记录 → 写研判 → 人工确认 AI 内容 → 提交给决策员。
 *
 * 契约要点（services/README.md、docs/workflow.md 第 3 节）：
 * - 报告只能引用「已指派给本人」的侦察记录，服务端会再核对一次；
 * - 提交时必须 `ai_content_confirmed=true`（fail-closed），所以界面上要求逐条处理 AI 建议；
 * - 提交后状态进入 `assigned`，草稿只由作者编辑。
 */
import { computed, ref, watch } from 'vue'
import { ApiError } from '../../api/client'
import { reconApi, reportApi } from '../../api/endpoints'
import {
  priorityNames,
  priorityOptions,
  reconStatusNames,
  riskNames,
  riskOptions,
  type AISuggestion,
  type AnalysisReport,
  type AnalysisReportWrite,
  type ReconRecord,
} from '../../api/types'
import AiSuggestionPanel from '../../components/AiSuggestionPanel.vue'
import AppDialog from '../../components/AppDialog.vue'
import CandidatePicker from '../../components/CandidatePicker.vue'
import StatusPill from '../../components/StatusPill.vue'
import { pushToast } from '../../stores/toast'
import { formatFull, truncate } from '../../utils/format'
import { newIdempotencyKey } from '../../utils/idempotency'
import { hasErrors, validateReport, type FieldErrors } from '../../utils/validation'

const props = defineProps<{ open: boolean; reportId: string | null; seedRecordId?: string | null }>()
const emit = defineEmits<{ close: []; changed: [] }>()

const report = ref<AnalysisReport | null>(null)
const suggestion = ref<AISuggestion | null>(null)
const available = ref<ReconRecord[]>([])
const loading = ref(false)
const saving = ref(false)
const submitting = ref(false)
const error = ref<ApiError | null>(null)
const errors = ref<FieldErrors>({})
const confirmOpen = ref(false)
const decisionMakerIds = ref<string[]>([])
const aiConfirmed = ref(false)

const draft = ref({
  title: '',
  recon_record_ids: [] as string[],
  key_findings: '',
  relations: '',
  risk_level: 'medium' as string,
  recommended_actions: '',
  priority: 'normal' as string,
})

let createKey = ''
let submitKey = ''

const isNew = computed(() => !props.reportId)
const editable = computed(() => isNew.value || report.value?.status === 'draft')

function reset() {
  report.value = null
  suggestion.value = null
  errors.value = {}
  error.value = null
  confirmOpen.value = false
  decisionMakerIds.value = []
  aiConfirmed.value = false
  createKey = ''
  submitKey = ''
  draft.value = {
    title: '',
    recon_record_ids: props.seedRecordId ? [props.seedRecordId] : [],
    key_findings: '',
    relations: '',
    risk_level: 'medium',
    recommended_actions: '',
    priority: 'normal',
  }
}

async function load() {
  reset()
  loading.value = true
  try {
    const page = await reconApi.list({ status: 'assigned', page_size: 50 })
    available.value = page.items
    if (props.reportId) {
      const value = await reportApi.get(props.reportId)
      report.value = value
      draft.value = {
        title: value.title,
        recon_record_ids: value.recon_links.map(link => link.recon_record_id),
        key_findings: value.key_findings,
        relations: value.relations ?? '',
        risk_level: value.risk_level,
        recommended_actions: value.recommended_actions,
        priority: value.priority,
      }
      aiConfirmed.value = value.ai_content_confirmed
    }
  } catch (cause) {
    error.value = cause instanceof ApiError ? cause : new ApiError(0, 'NETWORK_ERROR', '报告加载失败。')
  } finally {
    loading.value = false
  }
}

watch(() => [props.open, props.reportId], () => {
  if (props.open) void load()
})

function toggleRecord(id: string) {
  const list = draft.value.recon_record_ids
  draft.value.recon_record_ids = list.includes(id) ? list.filter(item => item !== id) : [...list, id]
}

async function saveDraft(): Promise<void> {
  errors.value = validateReport(draft.value)
  if (hasErrors(errors.value)) return
  saving.value = true
  error.value = null
  try {
    if (!report.value) {
      createKey ||= newIdempotencyKey()
      report.value = await reportApi.create(
        {
          title: draft.value.title,
          recon_record_ids: draft.value.recon_record_ids,
          key_findings: draft.value.key_findings,
          relations: draft.value.relations || undefined,
          risk_level: draft.value.risk_level as AnalysisReportWrite['risk_level'],
          recommended_actions: draft.value.recommended_actions,
          priority: draft.value.priority as AnalysisReportWrite['priority'],
        },
        createKey,
      )
      createKey = ''
      pushToast(`报告草稿已保存：${report.value.report_no}`, 'success')
    } else {
      report.value = await reportApi.patch(report.value.id, {
        expected_version: report.value.version,
        title: draft.value.title,
        key_findings: draft.value.key_findings,
        relations: draft.value.relations || undefined,
        risk_level: draft.value.risk_level as AnalysisReportWrite['risk_level'],
        recommended_actions: draft.value.recommended_actions,
        priority: draft.value.priority as AnalysisReportWrite['priority'],
      })
      pushToast('报告草稿已更新', 'success')
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
  errors.value = validateReport(draft.value)
  if (hasErrors(errors.value)) return
  confirmOpen.value = true
}

async function submitReport() {
  if (!report.value) return
  if (!decisionMakerIds.value.length) {
    pushToast('请至少选择一名决策员。', 'error')
    return
  }
  if (!aiConfirmed.value) {
    pushToast('提交前必须确认 AI 内容已逐条处理（接受/修改/舍弃）。', 'error')
    return
  }
  submitting.value = true
  error.value = null
  try {
    submitKey ||= newIdempotencyKey()
    report.value = await reportApi.submit(
      report.value.id,
      {
        expected_version: report.value.version,
        decision_maker_ids: decisionMakerIds.value,
        ai_content_confirmed: true,
      },
      submitKey,
    )
    submitKey = ''
    confirmOpen.value = false
    pushToast('分析报告已提交并指派决策员', 'success')
    emit('changed')
  } catch (cause) {
    const apiError = cause instanceof ApiError ? cause : new ApiError(0, 'NETWORK_ERROR', '提交失败。')
    error.value = apiError
    pushToast(apiError.message, 'error', apiError.conflict)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <AppDialog
    :open="open"
    :busy="saving || submitting"
    wide
    :eyebrow="isNew ? '02 / ORIENT · 新建' : `报告 ${report?.report_no ?? ''}`"
    :title="isNew ? '编写分析报告' : report?.title || '分析报告'"
    @close="emit('close')"
  >
    <p v-if="loading" class="muted" role="status"><span class="spinner" aria-hidden="true"></span> 正在加载报告与待分析记录…</p>
    <p v-else-if="error && !report" class="field-error" role="alert">{{ error.message }}</p>

    <template v-else>
      <div v-if="report" class="panel-meta">
        <StatusPill kind="report" :status="report.status" />
        <span class="muted">风险：{{ riskNames[report.risk_level] }} · 优先级：{{ priorityNames[report.priority] }}</span>
        <span class="muted">AI 内容已确认：{{ report.ai_content_confirmed ? '是' : '否' }}</span>
      </div>

      <template v-if="editable">
        <div class="form-field">
          <label for="report-title">标题 <span aria-hidden="true">*</span></label>
          <input id="report-title" v-model="draft.title" maxlength="200" :aria-invalid="!!errors.title" placeholder="例如：区域活动规律分析">
          <small class="field-error">{{ errors.title }}</small>
        </div>

        <fieldset class="candidate-picker">
          <legend>关联侦察记录 <span aria-hidden="true">*</span></legend>
          <p class="muted">只列出指派给你的记录；报告里的标题是提交时的不可变快照。</p>
          <p v-if="!available.length" class="muted">当前没有指派给你的侦察记录，等侦察员提交后再写报告。</p>
          <div v-else class="candidate-list">
            <label v-for="item in available" :key="item.id" class="check-label">
              <input
                type="checkbox"
                :checked="draft.recon_record_ids.includes(item.id)"
                :disabled="saving || (!!report && report.status !== 'draft')"
                @change="toggleRecord(item.id)"
              >
              <span>
                <strong>{{ item.title }}</strong>
                <small>{{ item.record_no }} · {{ reconStatusNames[item.status] }} · {{ truncate(item.content, 40) }}</small>
              </span>
            </label>
          </div>
          <small class="field-error">{{ errors.recon_record_ids }}</small>
        </fieldset>

        <div class="form-field">
          <label for="report-findings">关键发现 <span aria-hidden="true">*</span></label>
          <textarea id="report-findings" v-model="draft.key_findings" rows="5" maxlength="8000" :aria-invalid="!!errors.key_findings" placeholder="结论先行：这些信息合在一起说明了什么。"></textarea>
          <div class="input-meta">
            <small class="field-error">{{ errors.key_findings }}</small>
            <small>{{ draft.key_findings.length }} / 8000</small>
          </div>
        </div>
        <div class="form-field">
          <label for="report-relations">关联关系</label>
          <textarea id="report-relations" v-model="draft.relations" rows="3" maxlength="8000" placeholder="哪些线索在时间、地点或人员上互相印证。"></textarea>
          <small class="field-error">{{ errors.relations }}</small>
        </div>
        <div class="form-field">
          <label for="report-actions">建议手段 <span aria-hidden="true">*</span></label>
          <textarea id="report-actions" v-model="draft.recommended_actions" rows="3" maxlength="4000" :aria-invalid="!!errors.recommended_actions" placeholder="给决策员的行动建议。"></textarea>
          <small class="field-error">{{ errors.recommended_actions }}</small>
        </div>
        <div class="form-row">
          <div class="form-field">
            <label for="report-risk">风险等级 <span aria-hidden="true">*</span></label>
            <select id="report-risk" v-model="draft.risk_level">
              <option v-for="option in riskOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
            <small class="field-error">{{ errors.risk_level }}</small>
          </div>
          <div class="form-field">
            <label for="report-priority">优先级 <span aria-hidden="true">*</span></label>
            <select id="report-priority" v-model="draft.priority">
              <option v-for="option in priorityOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
            <small class="field-error">{{ errors.priority }}</small>
          </div>
        </div>

        <AiSuggestionPanel
          v-model:suggestion="suggestion"
          stage="analysis"
          object-type="analysis_report"
          :object-id="report?.id ?? ''"
          suggestion-type="entity_relation"
          :disabled="!report"
        />
      </template>

      <template v-else>
        <dl class="kv-grid">
          <div><dt>风险等级</dt><dd>{{ riskNames[report?.risk_level ?? 'low'] }}</dd></div>
          <div><dt>优先级</dt><dd>{{ priorityNames[report?.priority ?? 'normal'] }}</dd></div>
          <div><dt>提交时间</dt><dd>{{ formatFull(report?.submitted_at) }}</dd></div>
          <div><dt>人工确认</dt><dd>{{ report?.human_confirmed ? `已确认 ${formatFull(report.confirmed_at)}` : '未确认' }}</dd></div>
        </dl>
        <section class="detail-section">
          <p class="eyebrow">引用侦察记录</p>
          <ul class="evidence-list">
            <li v-for="link in report?.recon_links ?? []" :key="link.recon_record_id">
              <span>
                <strong>{{ link.recon_title_snapshot }}</strong>
                <small>{{ link.recon_record_id.slice(0, 8) }} · 关联于 {{ formatFull(link.linked_at) }}</small>
              </span>
            </li>
          </ul>
        </section>
        <section class="detail-section">
          <p class="eyebrow">关键发现</p>
          <p class="record-content">{{ report?.key_findings }}</p>
        </section>
        <section class="detail-section">
          <p class="eyebrow">关联关系</p>
          <p class="record-content">{{ report?.relations || '未填写' }}</p>
        </section>
        <section class="detail-section">
          <p class="eyebrow">建议手段</p>
          <p class="record-content">{{ report?.recommended_actions }}</p>
        </section>
      </template>

      <div v-if="confirmOpen" class="confirm-panel" role="alert">
        <span class="eyebrow">提交确认</span>
        <h3>{{ draft.title }}</h3>
        <CandidatePicker v-model="decisionMakerIds" target-role="decision_maker" role-label="指派决策员" :disabled="submitting" />
        <label class="check-label confirmation">
          <input v-model="aiConfirmed" type="checkbox" :disabled="submitting">
          我已逐条处理 AI 建议（接受、修改或舍弃），并确认报告结论由本人负责。
        </label>
        <p class="muted">提交后报告进入「已提交待研判」，作者不能再直接改写。</p>
      </div>

      <p v-if="error?.requestId" class="muted">请求 ID：{{ error.requestId }}</p>
    </template>

    <template #footer>
      <div class="actions footer-split">
        <span class="muted">* 为提交必填项</span>
        <div class="actions">
          <button v-if="editable" type="button" :disabled="saving || submitting" @click="saveDraft">
            {{ saving ? '正在保存…' : report ? '保存修改' : '保存草稿' }}
          </button>
          <button v-if="confirmOpen" type="button" :disabled="submitting" @click="confirmOpen = false">返回修改</button>
          <button v-if="editable && !confirmOpen" type="button" class="primary" :disabled="saving" @click="askSubmit">提交给决策员 →</button>
          <button v-if="confirmOpen" type="button" class="primary" :disabled="submitting || !decisionMakerIds.length || !aiConfirmed" @click="submitReport">
            {{ submitting ? '正在提交…' : '确认提交' }}
          </button>
        </div>
      </div>
    </template>
  </AppDialog>
</template>
