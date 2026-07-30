<template>
  <el-container class="app-layout">
    <Sidebar />
    <el-container class="app-layout__workspace">
      <Header />
      <PageTabs />
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
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
.app-layout { height: 100vh; min-width: 0; }
.app-layout__workspace { min-width: 0; }
.el-main { background: #f6f7f9; padding: 20px; overflow: auto; }
</style>
