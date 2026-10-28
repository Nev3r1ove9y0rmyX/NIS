/** 全局操作反馈：成功、失败、提示都从右上角出现，且不包含后端原始堆栈。 */
import { reactive } from 'vue'

export type ToastTone = 'success' | 'error' | 'info'

export interface Toast {
  id: number
  tone: ToastTone
  message: string
  /** 冲突类提示保留更久，用户需要看清原因。 */
  sticky?: boolean
}

let sequence = 0

export const toasts = reactive<{ items: Toast[] }>({ items: [] })

export function pushToast(message: string, tone: ToastTone = 'info', sticky = false): number {
  sequence += 1
  const toast: Toast = { id: sequence, tone, message, sticky }
  toasts.items.push(toast)
  if (!sticky) {
    setTimeout(() => dismissToast(toast.id), tone === 'error' ? 8000 : 4000)
  }
  return toast.id
}

export function dismissToast(id: number): void {
  const index = toasts.items.findIndex(item => item.id === id)
  if (index >= 0) toasts.items.splice(index, 1)
}

export function clearToasts(): void {
  toasts.items.splice(0, toasts.items.length)
}
