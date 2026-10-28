<script setup lang="ts">
import { dismissToast, toasts } from '../stores/toast'
</script>

<template>
  <div class="toast-host" aria-live="polite" aria-atomic="false">
    <p v-for="toast in toasts.items" :key="toast.id" class="toast" :data-tone="toast.tone" role="status">
      <span>{{ toast.message }}</span>
      <button aria-label="关闭提示" @click="dismissToast(toast.id)">×</button>
    </p>
  </div>
</template>
