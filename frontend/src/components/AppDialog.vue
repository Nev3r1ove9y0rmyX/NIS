<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{ open: boolean; title: string; eyebrow?: string; busy?: boolean; wide?: boolean }>(),
  { eyebrow: '', busy: false, wide: false },
)
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement>()

function sync(open: boolean) {
  const element = dialog.value
  if (!element) return
  if (open && !element.open) element.showModal()
  if (!open && element.open) element.close()
}

watch(() => props.open, sync)
onMounted(() => sync(props.open))
onUnmounted(() => dialog.value?.open && dialog.value.close())

function requestClose() {
  if (props.busy) return
  emit('close')
}
</script>

<template>
  <dialog
    ref="dialog"
    class="editor-dialog"
    :class="{ wide }"
    :aria-labelledby="`dialog-title-${title.length}`"
    @cancel.prevent="requestClose"
    @close="emit('close')"
  >
    <header class="dialog-header">
      <div>
        <span v-if="eyebrow" class="eyebrow">{{ eyebrow }}</span>
        <h2 :id="`dialog-title-${title.length}`">{{ title }}</h2>
      </div>
      <button class="icon-button" aria-label="关闭对话框" :disabled="busy" @click="requestClose">×</button>
    </header>
    <div class="dialog-body">
      <slot />
    </div>
    <footer v-if="$slots.footer" class="dialog-footer">
      <slot name="footer" />
    </footer>
  </dialog>
</template>
