<script setup lang="ts">
/**
 * 候选接收人选择器：人员范围由后端按组织与角色权限筛出，前端只负责展示与勾选
 * （C-06：不能把指令分配给不存在或无权限的用户）。
 */
import { onMounted, ref, computed } from 'vue'
import { ApiError } from '../api/client'
import { candidateApi } from '../api/endpoints'
import type { Candidate } from '../api/types'

const props = withDefaults(
  defineProps<{
    targetRole: string
    roleLabel: string
    modelValue: string[]
    single?: boolean
    disabled?: boolean
  }>(),
  { single: false, disabled: false },
)
const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>()

const candidates = ref<Candidate[]>([])
const loading = ref(false)
const error = ref<ApiError | null>(null)
const search = ref('')

const visible = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  if (!keyword) return candidates.value
  return candidates.value.filter(item =>
    `${item.display_name} ${item.organization?.name ?? ''}`.toLowerCase().includes(keyword),
  )
})

async function load() {
  loading.value = true
  error.value = null
  try {
    const page = await candidateApi.list(props.targetRole)
    candidates.value = page.items
  } catch (cause) {
    error.value = cause instanceof ApiError ? cause : new ApiError(0, 'NETWORK_ERROR', '候选列表加载失败。')
  } finally {
    loading.value = false
  }
}

function toggle(userId: string) {
  if (props.disabled) return
  const selected = props.modelValue
  if (props.single) {
    emit('update:modelValue', selected.includes(userId) ? [] : [userId])
    return
  }
  emit(
    'update:modelValue',
    selected.includes(userId) ? selected.filter(item => item !== userId) : [...selected, userId],
  )
}

onMounted(load)
defineExpose({ reload: load })
</script>

<template>
  <fieldset class="candidate-picker">
    <legend>{{ roleLabel }} <span aria-hidden="true">*</span></legend>
    <p class="muted">名单由服务端按「账号启用 + 角色有效 + 组织范围」筛选，不是前端写死的。</p>
    <label class="search-field candidate-search">
      <span aria-hidden="true">⌕</span>
      <input v-model="search" type="search" :aria-label="`搜索${roleLabel}`" placeholder="按名称或组织搜索" :disabled="disabled">
    </label>

    <p v-if="loading" class="muted" role="status"><span class="spinner" aria-hidden="true"></span> 正在加载候选人员…</p>
    <p v-else-if="error" class="field-error" role="alert">{{ error.message }}</p>
    <p v-else-if="!visible.length" class="muted">没有符合条件的{{ roleLabel }}，请联系管理员检查角色分配。</p>

    <div v-else class="candidate-list">
      <label v-for="item in visible" :key="item.user_id" class="check-label">
        <input
          type="checkbox"
          :checked="modelValue.includes(item.user_id)"
          :disabled="disabled"
          @change="toggle(item.user_id)"
        >
        <span>
          <strong>{{ item.display_name }}</strong>
          <small>{{ item.organization?.name || '未归属组织' }} · {{ item.role_code }}</small>
        </span>
      </label>
    </div>
    <small class="muted">已选 {{ modelValue.length }} 人</small>
  </fieldset>
</template>
