<template>
  <el-aside :width="collapsed ? '64px' : '220px'" class="sidebar">
    <div class="sidebar__brand">
      <span class="sidebar__brand-dot" />
      <span v-if="!collapsed" class="sidebar__brand-text">PetOps</span>
    </div>
    <el-menu
      :default-active="route.path"
      :default-openeds="defaultOpeneds"
      router
      :collapse="collapsed"
      unique-opened
      class="sidebar__menu"
    >
      <el-menu-item index="/dashboard" :route="{ path: '/dashboard' }">
        <el-icon><Histogram /></el-icon>
        <template #title>仪表盘</template>
      </el-menu-item>

      <el-sub-menu index="group-customer">
        <template #title>
          <el-icon><User /></el-icon>
          <span>客户运营</span>
        </template>
        <el-menu-item index="/customers" :route="{ path: '/customers' }">客户</el-menu-item>
        <el-menu-item index="/pets" :route="{ path: '/pets' }">宠物</el-menu-item>
        <el-menu-item index="/appointments" :route="{ path: '/appointments' }">预约</el-menu-item>
        <el-menu-item index="/business-hours" :route="{ path: '/business-hours' }">营业时间</el-menu-item>
        <el-menu-item index="/resources" :route="{ path: '/resources' }">美容资源</el-menu-item>
      </el-sub-menu>

      <el-sub-menu index="group-health">
        <template #title>
          <el-icon><TrendCharts /></el-icon>
          <span>健康监测</span>
        </template>
        <el-menu-item index="/health/metrics" :route="{ path: '/health/metrics' }">健康指标</el-menu-item>
        <el-menu-item index="/health/alerts" :route="{ path: '/health/alerts' }">健康告警</el-menu-item>
      </el-sub-menu>

      <el-sub-menu index="group-growth">
        <template #title>
          <el-icon><DataAnalysis /></el-icon>
          <span>增长运营</span>
        </template>
        <el-menu-item index="/operations/ltv" :route="{ path: '/operations/ltv' }">LTV 分群</el-menu-item>
        <el-menu-item index="/operations/churn" :route="{ path: '/operations/churn' }">流失风险</el-menu-item>
        <el-menu-item index="/marketing/contents" :route="{ path: '/marketing/contents' }">营销内容</el-menu-item>
        <el-menu-item index="/subscriptions" :route="{ path: '/subscriptions' }">订阅</el-menu-item>
      </el-sub-menu>

      <el-sub-menu index="group-supply">
        <template #title>
          <el-icon><Box /></el-icon>
          <span>供应链 &amp; 生态</span>
        </template>
        <el-menu-item index="/supply/skus" :route="{ path: '/supply/skus' }">SKU</el-menu-item>
        <el-menu-item index="/ecosystem/partners" :route="{ path: '/ecosystem/partners' }">合作医院</el-menu-item>
      </el-sub-menu>

      <el-menu-item index="/traces" :route="{ path: '/traces' }">
        <el-icon><Document /></el-icon>
        <template #title>对话追溯</template>
      </el-menu-item>
    </el-menu>
  </el-aside>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { computed } from 'vue'
import {
  Histogram, User, TrendCharts, DataAnalysis, Box, Document
} from '@element-plus/icons-vue'

const route = useRoute()
const app = useAppStore()
const collapsed = computed(() => app.sidebarCollapsed)

// 根据当前路径展开对应分组，使刷新页面 / 直接跳转时不会所有分组都收起。
const GROUP_PREFIXES: Record<string, string> = {
  '/customers': 'group-customer',
  '/pets': 'group-customer',
  '/appointments': 'group-customer',
  '/business-hours': 'group-customer',
  '/resources': 'group-customer',
  '/health': 'group-health',
  '/operations': 'group-growth',
  '/marketing': 'group-growth',
  '/subscriptions': 'group-growth',
  '/supply': 'group-supply',
  '/ecosystem': 'group-supply'
}
const defaultOpeneds = computed(() => {
  const match = Object.entries(GROUP_PREFIXES).find(([prefix]) =>
    route.path.startsWith(prefix)
  )
  return match ? [match[1]] : []
})
</script>

<style scoped>
.sidebar {
  background: #1a1c23;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}
.sidebar__brand {
  height: 56px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  flex-shrink: 0;
}
.sidebar__brand-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #f2b90c;
  flex-shrink: 0;
}
.sidebar__brand-text {
  color: #fff;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 0.5px;
}
.sidebar :deep(.el-menu) { border-right: none; background: transparent; flex: 1; }
.sidebar :deep(.el-menu-item),
.sidebar :deep(.el-sub-menu__title) { color: rgba(255, 255, 255, 0.75); }
.sidebar :deep(.el-menu-item:hover),
.sidebar :deep(.el-sub-menu__title:hover) { background: rgba(255, 255, 255, 0.06); color: #fff; }
.sidebar :deep(.el-menu-item.is-active) {
  background: rgba(242, 185, 12, 0.16);
  color: #f2b90c;
  border-right: 2px solid #f2b90c;
}
.sidebar :deep(.el-sub-menu .el-menu-item) { background: rgba(0, 0, 0, 0.15); }
</style>
