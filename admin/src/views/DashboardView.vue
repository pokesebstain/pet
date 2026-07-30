<template>
  <div class="dashboard">
    <h2>仪表盘</h2>

    <TodoPanel :todos="todos" />

    <el-row :gutter="12">
      <el-col :span="6">
        <StatCard
          label="今日预约"
          :value="stats.today_appointments"
          :sparkline="appointmentsSpark"
          @click="$router.push('/appointments')"
        />
      </el-col>
      <el-col :span="6">
        <StatCard
          label="今日新增客户"
          :value="stats.today_new_customers"
          :sparkline="customersSpark"
          color="#409eff"
          @click="$router.push('/customers')"
        />
      </el-col>
      <el-col :span="6">
        <StatCard
          label="待处理告警"
          :value="stats.pending_alerts"
          :sparkline="alertsSpark"
          color="#f56c6c"
          @click="$router.push('/health/alerts')"
        />
      </el-col>
      <el-col :span="6">
        <StatCard label="低库存 SKU" :value="stats.low_stock_skus" @click="$router.push('/supply/skus')" />
      </el-col>
    </el-row>
    <el-row :gutter="12">
      <el-col :span="12">
        <StatCard label="本月营收 (元)" :value="stats.recent_revenue" />
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import StatCard from '@/components/common/StatCard.vue'
import TodoPanel from '@/components/common/TodoPanel.vue'
import { dashboardApi, type OverviewStats, type Todo } from '@/api/dashboard'

const stats = ref<OverviewStats>({
  today_appointments: 0,
  today_new_customers: 0,
  pending_alerts: 0,
  low_stock_skus: 0,
  recent_revenue: 0
})
const todos = ref<Todo[]>([])
const appointmentsSpark = ref<number[]>([])
const customersSpark = ref<number[]>([])
const alertsSpark = ref<number[]>([])

onMounted(async () => {
  try {
    stats.value = await dashboardApi.overview()
  } catch (e) { /* interceptor 已 toast */ }
  try {
    todos.value = await dashboardApi.todos()
  } catch (e) { /* interceptor 已 toast */ }
  try {
    const points = await dashboardApi.trends(7)
    appointmentsSpark.value = points.map((p) => p.appointments)
    customersSpark.value = points.map((p) => p.new_customers)
    alertsSpark.value = points.map((p) => p.health_alerts)
  } catch (e) { /* interceptor 已 toast */ }
})
</script>

<style scoped>
.dashboard h2 { margin-bottom: 16px; }
</style>
