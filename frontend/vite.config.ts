import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

/**
 * 开发服务器把 `/api/v1` 反代到 Gateway：浏览器同源访问，因此不需要后端开 CORS
 * （正式部署由 deploy/nginx 做同样的同源反代）。
 *
 * 默认目标是 `http://127.0.0.1:8000`；本机 8000 被占用时在 `frontend/.env` 里写
 * `VITE_DEV_API_TARGET=http://127.0.0.1:8010` 即可覆盖。
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_DEV_API_TARGET || 'http://127.0.0.1:8000'
  const proxy = { '/api/v1': { target, changeOrigin: false, ws: false } }

  return {
    plugins: [vue()],
    server: {
      port: 5173,
      strictPort: false,
      proxy,
      // 编辑器/工具写文件时会生成临时目录，Windows 上监听它会 EBUSY 并带崩 dev server。
      watch: { ignored: ['**/.*.tmpdir/**', '**/*.tmpdir/**', '**/*.tmp', '**/.*.tmp'] },
    },
    preview: { proxy },
    test: {
      include: ['src/**/*.test.ts'],
      environment: 'jsdom',
      restoreMocks: true,
      clearMocks: true,
    },
  }
})
