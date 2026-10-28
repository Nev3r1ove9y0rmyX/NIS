<script setup lang="ts">
/**
 * 二次确认：所有不可逆或跨角色的关键动作都要经过这里
 * （C-08：危险操作二次确认，且确认内容说清「会发生什么」）。
 */
import AppDialog from './AppDialog.vue'

withDefaults(
  defineProps<{
    open: boolean
    title: string
    confirmText: string
    busy?: boolean
    danger?: boolean
  }>(),
  { busy: false, danger: false },
)
const emit = defineEmits<{ confirm: []; cancel: [] }>()
</script>

<template>
  <AppDialog :open="open" :title="title" eyebrow="请再次确认" :busy="busy" @close="emit('cancel')">
    <slot />
    <template #footer>
      <div class="actions">
        <button type="button" :disabled="busy" @click="emit('cancel')">返回修改</button>
        <button
          type="button"
          :class="danger ? 'danger-button' : 'primary'"
          :disabled="busy"
          @click="emit('confirm')"
        >
          {{ busy ? '正在处理…' : confirmText }}
        </button>
      </div>
    </template>
  </AppDialog>
</template>
