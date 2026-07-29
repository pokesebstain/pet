<template>
  <div>
    <h2>仪表盘</h2>
    <el-row :gutter="12">
      <el-col :span="6"><StatCard label="今日预约" :value="stats.today_appointments ?? 0" /></el-col>
      <el-col :span="6"><StatCard label="今日新增客户" :value="stats.today_new_customers ?? 0" /></el-col>
      <el-col :span="6"><StatCard label="待处理告警" :value="stats.pending_alerts ?? 0" /></el-col>
      <el-col :span="6"><StatCard label="低库存 SKU" :value="stats.low_stock_skus ?? 0" /></el-col>
    </el-row>
    <el-row :gutter="12">
      <el-col :span="12"><StatCard label="本月营收 (元)" :value="stats.recent_revenue ?? 0" /></el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { http } from '@/api/client'
import StatCard from '@/components/common/StatCard.vue'

interface Stats {
  today_appointments: number
  today_new_customers: number
  pending_alerts: number
  low_stock_skus: number
  recent_revenue: number
}

const stats = ref<Stats>({
  today_appointments: 0,
  today_new_customers: 0,
  pending_alerts: 0,
  low_stock_skus: 0,
  recent_revenue: 0
})

onMounted(async () => {
  try {
    const { data } = await http.get<Stats>('/stats/overview')
    stats.value = data
  } catch (e) { /* interceptor 已 toast */ }
})
</script>
