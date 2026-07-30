import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export interface WorkspaceTab {
  path: string
  title: string
  closable: boolean
}

export const WORKSPACE_STORAGE_KEY = 'petops.admin.workspace'
const DASHBOARD_TAB: WorkspaceTab = { path: '/dashboard', title: '仪表盘', closable: false }

function readStoredWorkspace(): { tabs: unknown; activeTabPath: unknown } | null {
  try {
    const raw = sessionStorage.getItem(WORKSPACE_STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export const useAppStore = defineStore('app', () => {
  const sidebarCollapsed = ref(false)
  const tabs = ref<WorkspaceTab[]>([{ ...DASHBOARD_TAB }])
  const activeTabPath = ref(DASHBOARD_TAB.path)

  watch([tabs, activeTabPath], () => {
    sessionStorage.setItem(WORKSPACE_STORAGE_KEY, JSON.stringify({ tabs: tabs.value, activeTabPath: activeTabPath.value }))
  }, { deep: true })

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  function restoreTabs(isValidRoute: (path: string) => boolean) {
    const saved = readStoredWorkspace()
    const restored: WorkspaceTab[] = [{ ...DASHBOARD_TAB }]
    const seen = new Set([DASHBOARD_TAB.path])
    if (Array.isArray(saved?.tabs)) {
      for (const item of saved.tabs) {
        if (!item || typeof item !== 'object') continue
        const { path, title } = item as Partial<WorkspaceTab>
        if (typeof path !== 'string' || typeof title !== 'string' || seen.has(path) || !isValidRoute(path)) continue
        seen.add(path)
        restored.push({ path, title: title.trim() || '工作页面', closable: path !== DASHBOARD_TAB.path })
      }
    }
    tabs.value = restored
    activeTabPath.value = typeof saved?.activeTabPath === 'string' && seen.has(saved.activeTabPath)
      ? saved.activeTabPath
      : DASHBOARD_TAB.path
  }

  function openTab(tab: WorkspaceTab) {
    const existing = tabs.value.find(item => item.path === tab.path)
    if (existing) {
      existing.title = tab.title
      existing.closable = tab.path !== DASHBOARD_TAB.path
    } else {
      tabs.value.push({ ...tab, closable: tab.path !== DASHBOARD_TAB.path })
    }
    activeTabPath.value = tab.path
  }

  function setActiveTab(path: string) {
    if (tabs.value.some(tab => tab.path === path)) activeTabPath.value = path
  }

  function closeTab(path: string): string | null {
    const index = tabs.value.findIndex(tab => tab.path === path)
    if (index < 0 || path === DASHBOARD_TAB.path) return null
    const wasActive = activeTabPath.value === path
    tabs.value.splice(index, 1)
    if (!wasActive) return null
    const next = tabs.value[index] || tabs.value[index - 1] || DASHBOARD_TAB
    activeTabPath.value = next.path
    return next.path
  }

  return { sidebarCollapsed, tabs, activeTabPath, toggleSidebar, restoreTabs, openTab, setActiveTab, closeTab }
})
