<template>
  <el-aside :width="collapsed ? '64px' : '220px'" class="sidebar">
    <el-menu
      :default-active="route.path"
      router
      :collapse="collapsed"
      class="sidebar__menu"
    >
      <el-menu-item index="/dashboard" :route="{ path: '/dashboard' }">
        <el-icon><Histogram /></el-icon>
        <template #title>仪表盘</template>
      </el-menu-item>
      <el-menu-item index="/customers" :route="{ path: '/customers' }">
        <el-icon><User /></el-icon>
        <template #title>客户</template>
      </el-menu-item>
      <el-menu-item index="/pets" :route="{ path: '/pets' }">
        <el-icon><Sunny /></el-icon>
        <template #title>宠物</template>
      </el-menu-item>
      <el-menu-item index="/appointments" :route="{ path: '/appointments' }">
        <el-icon><Calendar /></el-icon>
        <template #title>预约</template>
      </el-menu-item>
      <el-menu-item index="/business-hours" :route="{ path: '/business-hours' }">
        <el-icon><Clock /></el-icon>
        <template #title>营业时间</template>
      </el-menu-item>
      <el-menu-item index="/resources" :route="{ path: '/resources' }">
        <el-icon><Tools /></el-icon>
        <template #title>美容资源</template>
      </el-menu-item>
      <el-menu-item index="/health/metrics" :route="{ path: '/health/metrics' }">
        <el-icon><TrendCharts /></el-icon>
        <template #title>健康指标</template>
      </el-menu-item>
      <el-menu-item index="/health/alerts" :route="{ path: '/health/alerts' }">
        <el-icon><Bell /></el-icon>
        <template #title>健康告警</template>
      </el-menu-item>
      <el-menu-item index="/operations/ltv" :route="{ path: '/operations/ltv' }">
        <el-icon><DataAnalysis /></el-icon>
        <template #title>LTV 分群</template>
      </el-menu-item>
      <el-menu-item index="/operations/churn" :route="{ path: '/operations/churn' }">
        <el-icon><Warning /></el-icon>
        <template #title>流失风险</template>
      </el-menu-item>
      <el-menu-item index="/supply/skus" :route="{ path: '/supply/skus' }">
        <el-icon><Box /></el-icon>
        <template #title>SKU</template>
      </el-menu-item>
      <el-menu-item index="/marketing/contents" :route="{ path: '/marketing/contents' }">
        <el-icon><Promotion /></el-icon>
        <template #title>营销内容</template>
      </el-menu-item>
      <el-menu-item index="/subscriptions" :route="{ path: '/subscriptions' }">
        <el-icon><CreditCard /></el-icon>
        <template #title>订阅</template>
      </el-menu-item>
      <el-menu-item index="/ecosystem/partners" :route="{ path: '/ecosystem/partners' }">
        <el-icon><Share /></el-icon>
        <template #title>合作医院</template>
      </el-menu-item>
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
  Histogram, User, Sunny, Calendar, Clock, Tools, TrendCharts,
  Bell, DataAnalysis, Warning, Box, Promotion, CreditCard, Share, Document
} from '@element-plus/icons-vue'

const route = useRoute()
const app = useAppStore()
const collapsed = computed(() => app.sidebarCollapsed)
</script>

<style scoped>
.sidebar { background: #001529; min-height: 100vh; }
.sidebar :deep(.el-menu) { border-right: none; background: transparent; }
.sidebar :deep(.el-menu-item) { color: #fff; }
</style>
