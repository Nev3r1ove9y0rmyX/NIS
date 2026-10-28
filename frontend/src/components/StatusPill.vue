<script setup lang="ts">
import { computed } from 'vue'
import { statusLabel, statusTone, type StatusKind } from '../api/types'

const props = defineProps<{ kind: StatusKind; status: string }>()
const label = computed(() => statusLabel(props.kind, props.status))
const tone = computed(() => statusTone(props.status))
</script>

<template>
  <span class="status-badge" :data-tone="tone">{{ label }}</span>
</template>
