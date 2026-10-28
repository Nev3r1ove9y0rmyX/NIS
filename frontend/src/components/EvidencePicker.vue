<script setup lang="ts">
/**
 * 证据选择器。
 *
 * 契约现状（docs/frontend-integration.md 第 4 节）：只有「证据元数据 + 受控目录下载」，
 * 没有上传端点。因此这里选择文件后：校验类型/大小 → 浏览器内算 sha256 →
 * 作为元数据随业务提交；页面上明确告知「文件本体未上传，下载可能返回 404」，
 * 不把未发生的事显示成已上传。
 */
import { ref } from 'vue'
import type { EvidenceInput } from '../api/types'
import { formatBytes } from '../utils/format'
import { sha256OfFile } from '../utils/sha256'
import { evidenceLimitError, validateEvidenceFile } from '../utils/validation'

const props = withDefaults(
  defineProps<{ modelValue: EvidenceInput[]; disabled?: boolean }>(),
  { disabled: false },
)
const emit = defineEmits<{ 'update:modelValue': [value: EvidenceInput[]] }>()

const error = ref('')
const hashing = ref(false)
const input = ref<HTMLInputElement>()

async function onChange(event: Event) {
  const target = event.target as HTMLInputElement
  const files = Array.from(target.files ?? [])
  target.value = ''
  error.value = ''
  if (!files.length) return

  const next = [...props.modelValue]
  hashing.value = true
  try {
    for (const file of files) {
      const limit = evidenceLimitError(next.length)
      if (limit) {
        error.value = limit
        break
      }
      const invalid = validateEvidenceFile(file)
      if (invalid) {
        error.value = `${file.name}：${invalid}`
        continue
      }
      const digest = await sha256OfFile(file)
      next.push({
        file_name: file.name,
        media_type: file.type || 'application/octet-stream',
        size_bytes: file.size,
        sha256: digest,
      })
    }
    emit('update:modelValue', next)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '文件摘要计算失败。'
  } finally {
    hashing.value = false
  }
}

function remove(index: number) {
  const next = [...props.modelValue]
  next.splice(index, 1)
  emit('update:modelValue', next)
}
</script>

<template>
  <div class="form-field">
    <label for="evidence-input">证据文件（PNG / JPEG / PDF / TXT，单个 ≤10 MB，最多 5 份）</label>
    <input
      id="evidence-input"
      ref="input"
      type="file"
      multiple
      accept=".png,.jpg,.jpeg,.pdf,.txt"
      :disabled="disabled || hashing"
      @change="onChange"
    >
    <small class="muted">
      选择后由浏览器计算 sha256 作为证据元数据提交；当前契约没有上传端点，文件本体不会进入服务器受控目录。
    </small>
    <p v-if="hashing" class="muted" role="status"><span class="spinner" aria-hidden="true"></span> 正在计算文件摘要…</p>
    <p v-if="error" class="field-error" role="alert">{{ error }}</p>
    <ul v-if="modelValue.length" class="evidence-list">
      <li v-for="(item, index) in modelValue" :key="item.sha256">
        <span>
          <strong>{{ item.file_name }}</strong>
          <small>{{ formatBytes(item.size_bytes) }} · sha256 {{ item.sha256.slice(0, 12) }}…</small>
        </span>
        <button type="button" :aria-label="`移除 ${item.file_name}`" :disabled="disabled" @click="remove(index)">移除</button>
      </li>
    </ul>
  </div>
</template>
