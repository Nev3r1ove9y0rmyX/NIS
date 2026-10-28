<script setup lang="ts">
/**
 * 列表页三态：加载 / 失败 / 空数据。
 *
 * 失败时区分「网络不可用、无权限、状态冲突」三类，并给出可执行的下一步，
 * 而不是只在控制台打印错误（C-08）。
 */
import { computed } from 'vue'
import { ApiError } from '../api/client'

const props = withDefaults(
  defineProps<{
    loading?: boolean
    error?: ApiError | null
    empty?: boolean
    emptyTitle?: string
    emptyHint?: string
  }>(),
  {
    loading: false,
    error: null,
    empty: false,
    emptyTitle: '这里还没有数据',
    emptyHint: '完成一次业务操作后，记录会出现在这里。',
  },
)
const emit = defineEmits<{ retry: [] }>()

const errorTitle = computed(() => {
  const error = props.error
  if (!error) return ''
  if (error.offline) return '无法连接服务'
  if (error.forbidden) return '没有查看权限'
  if (error.notFound) return '记录不存在或已不可访问'
  if (error.versionConflict) return '记录已被其他成员更新'
  if (error.workflowConflict) return '当前状态不允许该操作'
  if (error.unauthorized) return '登录已失效'
  return '暂时无法加载数据'
})
</script>

<template>
  <div v-if="loading" class="empty-state" role="status" aria-busy="true">
    <span class="spinner" aria-hidden="true"></span>
    <h3>正在加载…</h3>
    <p>数据来自后端接口，请稍候。</p>
  </div>
  <div v-else-if="error" class="empty-state" role="alert">
    <span class="empty-symbol" aria-hidden="true">!</span>
    <h3>{{ errorTitle }}</h3>
    <p>{{ error.message }}</p>
    <p v-if="error.requestId" class="muted">请求 ID：{{ error.requestId }}（报障时提供这一条）</p>
    <button v-if="error.retryable" @click="emit('retry')">重新加载</button>
  </div>
  <div v-else-if="empty" class="empty-state">
    <span class="empty-symbol" aria-hidden="true">▤</span>
    <h3>{{ emptyTitle }}</h3>
    <p>{{ emptyHint }}</p>
    <slot name="empty-action" />
  </div>
  <slot v-else />
</template>
