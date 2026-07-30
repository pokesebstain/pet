import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAppStore, WORKSPACE_STORAGE_KEY } from '@/stores/app'

describe('workspace tabs store', () => {
  beforeEach(() => {
    sessionStorage.clear()
    setActivePinia(createPinia())
  })

  it('keeps dashboard open and switches to the right tab when closing the active tab', () => {
    const store = useAppStore()
    store.openTab({ path: '/customers', title: '客户管理', closable: true })
    store.openTab({ path: '/pets', title: '宠物档案', closable: true })
    store.setActiveTab('/customers')

    expect(store.closeTab('/customers')).toBe('/pets')
    expect(store.tabs.map(tab => tab.path)).toEqual(['/dashboard', '/pets'])
    expect(store.activeTabPath).toBe('/pets')
    expect(store.closeTab('/dashboard')).toBeNull()
  })

  it('deduplicates and validates restored workspace tabs', () => {
    sessionStorage.setItem(WORKSPACE_STORAGE_KEY, JSON.stringify({
      tabs: [
        { path: '/dashboard', title: '旧首页', closable: true },
        { path: '/customers', title: '客户管理', closable: true },
        { path: '/customers', title: '重复客户', closable: true },
        { path: '/login', title: '登录', closable: true },
        { path: '/unknown', title: '无效页', closable: true }
      ],
      activeTabPath: '/login'
    }))

    const store = useAppStore()
    store.restoreTabs(path => ['/dashboard', '/customers'].includes(path))

    expect(store.tabs).toEqual([
      { path: '/dashboard', title: '仪表盘', closable: false },
      { path: '/customers', title: '客户管理', closable: true }
    ])
    expect(store.activeTabPath).toBe('/dashboard')
  })
})
