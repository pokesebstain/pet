<template>
  <div class="app-layout">
    <Sidebar />
    <section class="app-layout__workspace" aria-label="管理后台工作区">
      <Header />
      <PageTabs />
      <main class="app-layout__main">
        <router-view />
      </main>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Sidebar from './Sidebar.vue'
import Header from './Header.vue'
import PageTabs from './PageTabs.vue'
import { useAppStore } from '@/stores/app'

const app = useAppStore()
const route = useRoute()
const router = useRouter()

function isWorkspaceRoute(path: string): boolean {
  const resolved = router.resolve(path)
  return resolved.matched.length > 0 && !resolved.matched.some(record => record.meta.public)
}

function syncRouteTab() {
  if (!route.meta.public) {
    app.openTab({
      path: route.fullPath,
      title: String(route.meta.title || '工作页面'),
      closable: route.path !== '/dashboard'
    })
  }
}

onMounted(() => {
  app.restoreTabs(isWorkspaceRoute)
  syncRouteTab()
})
watch(() => route.fullPath, syncRouteTab)
</script>

<style scoped>
.app-layout {
  display: flex;
  width: 100%;
  min-width: 0;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
.app-layout__workspace {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}
.app-layout__workspace > :deep(.header),
.app-layout__workspace > :deep(.page-tabs) {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  flex: 0 0 auto;
}
.app-layout__main {
  flex: 1 1 auto;
  width: 100%;
  min-width: 0;
  min-height: 0;
  box-sizing: border-box;
  background: #f6f7f9;
  padding: 20px;
  overflow: auto;
}
.app-layout__main > :deep(*) {
  min-width: 0;
}
</style>
