<script setup lang="ts">
/**
 * AI 建议面板：人在回路的四段一致模式（docs/workflow.md 第 7 节）。
 *
 * 请求 → 展示建议原文 → 人工接受 / 修改 / 舍弃 → 人工确认后才允许正式提交。
 * 三件事分开显示与审计：AI 请求、人工确认、正式提交；AI 内容永远不进业务字段本身。
 */
import { computed, ref } from 'vue'
import { ApiError } from '../api/client'
import { aiApi } from '../api/endpoints'
import { aiStatusNames, type AIStage, type AISuggestion } from '../api/types'
import { formatFull } from '../utils/format'
import { pushToast } from '../stores/toast'

const props = withDefaults(
  defineProps<{
    stage: AIStage
    objectType: 'recon_record' | 'analysis_report' | 'command' | 'assignment'
    objectId: string
    suggestionType: string
    suggestion: AISuggestion | null
    disabled?: boolean
  }>(),
  { disabled: false },
)
const emit = defineEmits<{
  'update:suggestion': [value: AISuggestion]
  decided: [value: AISuggestion]
}>()

const requesting = ref(false)
const deciding = ref(false)
const error = ref('')
const editing = ref(false)
const headline = ref('')
const itemsText = ref('')
const caveat = ref('')

const content = computed(() => (props.suggestion?.content ?? {}) as Record<string, unknown>)
const headlineText = computed(() => (typeof content.value.headline === 'string' ? content.value.headline : ''))
const items = computed(() =>
  Array.isArray(content.value.items) ? content.value.items.filter((item): item is string => typeof item === 'string') : [],
)
const caveatText = computed(() => (typeof content.value.caveat === 'string' ? content.value.caveat : ''))
const pending = computed(() => props.suggestion?.status === 'pending')
const editedView = computed(() => (props.suggestion?.edited_content ?? {}) as Record<string, unknown>)

async function requestSuggestion() {
  if (requesting.value || !props.objectId) return
  requesting.value = true
  error.value = ''
  try {
    const suggestion = await aiApi.create({
      stage: props.stage,
      business_object_type: props.objectType,
      business_object_id: props.objectId,
      suggestion_type: props.suggestionType,
    })
    emit('update:suggestion', suggestion)
    // 先只展示建议原文；要修改时由用户点「修改建议」进入编辑态。
    editing.value = false
  } catch (cause) {
    if (cause instanceof ApiError && (cause.status === 503 || cause.status === 504)) {
      error.value = 'AI 服务当前不可用，可以继续人工填写并提交，AI 只影响建议功能。'
    } else {
      error.value = cause instanceof ApiError ? cause.message : 'AI 建议请求失败，请稍后重试。'
    }
  } finally {
    requesting.value = false
  }
}

function beginEdit(suggestion: AISuggestion | null = props.suggestion) {
  const body = (suggestion?.content ?? {}) as Record<string, unknown>
  headline.value = typeof body.headline === 'string' ? body.headline : ''
  itemsText.value = Array.isArray(body.items) ? body.items.join('\n') : ''
  caveat.value = typeof body.caveat === 'string' ? body.caveat : ''
  editing.value = true
}

async function decide(decision: 'accepted' | 'edited' | 'rejected') {
  if (!props.suggestion || deciding.value) return
  deciding.value = true
  error.value = ''
  try {
    const body =
      decision === 'edited'
        ? {
            decision,
            edited_content: {
              headline: headline.value,
              items: itemsText.value.split('\n').map(line => line.trim()).filter(Boolean),
              caveat: caveat.value,
            },
            note: '人工修改后采用',
          }
        : { decision }
    const updated = await aiApi.decide(props.suggestion.id, body)
    emit('update:suggestion', updated)
    emit('decided', updated)
    editing.value = false
    pushToast(`AI 建议处理结果：${aiStatusNames[updated.status]}`, 'success')
  } catch (cause) {
    const message = cause instanceof ApiError ? cause.message : '处理 AI 建议失败，请稍后重试。'
    error.value = message
    pushToast(message, 'error')
  } finally {
    deciding.value = false
  }
}
</script>

<template>
  <section class="ai-panel" aria-label="AI 建议（需人工确认）">
    <header>
      <div>
        <strong>AI 建议 · 待人工确认</strong>
        <small>规则模板生成，仅供参考；未经你确认不会写入业务字段。</small>
      </div>
      <span class="status-badge" data-tone="waiting">{{ suggestion ? aiStatusNames[suggestion.status] : '未请求' }}</span>
    </header>

    <div v-if="!suggestion" class="ai-empty">
      <p class="muted">可以请求一次 AI 摘要作为起草参考，也可以直接人工填写。</p>
      <button type="button" :disabled="requesting || disabled || !objectId" @click="requestSuggestion">
        {{ requesting ? '正在请求建议…' : '请求 AI 建议' }}
      </button>
      <p v-if="!objectId" class="muted">先保存草稿，拿到记录 ID 后才能请求建议。</p>
    </div>

    <template v-else>
      <dl class="kv-grid">
        <div><dt>模型</dt><dd>{{ suggestion.model_name }}<template v-if="suggestion.model_version"> · {{ suggestion.model_version }}</template></dd></div>
        <div><dt>置信度</dt><dd>{{ suggestion.confidence ?? '—' }}</dd></div>
        <div><dt>来源</dt><dd>{{ suggestion.source_refs?.join('、') || '—' }}</dd></div>
        <div><dt>生成时间</dt><dd>{{ formatFull(suggestion.created_at) }}</dd></div>
      </dl>

      <div v-if="!editing" class="ai-content">
        <p class="eyebrow">建议原文</p>
        <h4>{{ headlineText || '（无标题建议）' }}</h4>
        <ul v-if="items.length"><li v-for="item in items" :key="item">{{ item }}</li></ul>
        <p v-if="caveatText" class="muted">{{ caveatText }}</p>
      </div>

      <div v-else class="ai-editor">
        <p class="eyebrow">人工修改（修改后采用会记录为 edited）</p>
        <div class="form-field">
          <label for="ai-headline">建议标题</label>
          <input id="ai-headline" v-model="headline" maxlength="200" :disabled="!pending || deciding">
        </div>
        <div class="form-field">
          <label for="ai-items">要点（每行一条）</label>
          <textarea id="ai-items" v-model="itemsText" rows="4" :disabled="!pending || deciding"></textarea>
        </div>
        <div class="form-field">
          <label for="ai-caveat">保留说明</label>
          <input id="ai-caveat" v-model="caveat" maxlength="300" :disabled="!pending || deciding">
        </div>
      </div>

      <div v-if="suggestion.status !== 'pending'" class="ai-confirmed">
        <p>
          人工处理结果：<strong>{{ aiStatusNames[suggestion.status] }}</strong>
          <template v-if="suggestion.human_confirmed_at"> · {{ formatFull(suggestion.human_confirmed_at) }}</template>
        </p>
        <p v-if="suggestion.edited_content" class="muted">
          已采用你修改后的内容：{{ (editedView.headline as string) || '（标题未改）' }}
        </p>
      </div>

      <div class="actions ai-actions">
        <button type="button" class="primary" :disabled="!pending || deciding || disabled" @click="decide('accepted')">
          接受建议
        </button>
        <button type="button" :disabled="!pending || deciding || disabled" @click="editing ? decide('edited') : beginEdit()">
          {{ editing ? '修改后采用' : '修改建议' }}
        </button>
        <button type="button" :disabled="!pending || deciding || disabled" @click="decide('rejected')">舍弃</button>
      </div>
    </template>

    <p v-if="error" class="field-error" role="alert">{{ error }}</p>
  </section>
</template>
