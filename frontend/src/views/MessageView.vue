<script setup lang="ts">
import { homePath, session } from '../stores/session'

defineProps<{ code: string; title: string; message: string }>()
</script>
<template>
  <main class="message-page">
    <div class="eyebrow">NIS / {{ code }}</div>
    <h1>{{ title }}</h1>
    <p>{{ message }}</p>
    <div class="actions">
      <RouterLink class="button primary" :to="session.user ? homePath() : '/login'">
        {{ session.user ? '返回工作台' : '返回登录' }}
      </RouterLink>
      <button v-if="code === '503'" @click="$router.go(-1)">重试恢复</button>
    </div>
  </main>
</template>
