/**
 * 分页列表状态：加载 / 失败 / 空 / 分页 / 刷新 的行为在所有列表页保持一致（C-08）。
 */
import { reactive } from 'vue'
import { ApiError } from '../api/client'
import type { Page } from '../api/types'

export interface PagedQuery {
  page: number
  page_size: number
}

export interface ListState<T> {
  items: T[]
  total: number
  page: number
  pageSize: number
  loading: boolean
  error: ApiError | null
  loaded: boolean
}

export function usePagedList<T>(
  fetchPage: (query: PagedQuery) => Promise<Page<T>>,
  pageSize = 10,
) {
  const state = reactive<ListState<T>>({
    items: [],
    total: 0,
    page: 1,
    pageSize,
    loading: false,
    error: null,
    loaded: false,
  }) as ListState<T>

  async function load(page = state.page, options: { silent?: boolean } = {}): Promise<void> {
    state.loading = !options.silent
    state.error = null
    try {
      const result = await fetchPage({ page, page_size: state.pageSize })
      state.items = result.items
      state.total = result.total
      state.page = result.page || page
      state.loaded = true
    } catch (cause) {
      state.error = cause instanceof ApiError ? cause : new ApiError(0, 'NETWORK_ERROR', '列表加载失败。')
      state.items = []
      state.total = 0
    } finally {
      state.loading = false
    }
  }

  function pages(): number {
    return Math.max(1, Math.ceil(state.total / state.pageSize))
  }

  async function goto(page: number): Promise<void> {
    const target = Math.min(Math.max(1, page), pages())
    if (target === state.page) return
    await load(target)
  }

  return { state, load, goto, pages, reset: () => { state.page = 1 } }
}
