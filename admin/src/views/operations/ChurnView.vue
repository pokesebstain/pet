<template>
  <div>
    <h2>流失风险</h2>
    <el-input-number
      v-model="threshold"
      :min="0"
      :max="1"
      :step="0.05"
      @change="reload"
      style="margin-bottom: 12px"
    />
    <span style="margin-left: 8px; color: #909399">流失概率阈值 (0~1)</span>
    <el-table :data="items" v-loading="loading" border>
      <el-table-column prop="customer_id" label="客户 ID" />
      <el-table-column prop="name" label="姓名" />
      <el-table-column prop="churn_score" label="流失概率">
        <template #default="{ row }">
          <el-tag :type="row.churn_score > 0.7 ? 'danger' : 'warning'">
            {{ (row.churn_score * 100).toFixed(0) }}%
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="last_visit_at" label="最近到店">
        <template #default="{ row }">{{ row.last_visit_at ? formatDateTime(row.last_visit_at) : '-' }}</template>
      </el-table-column>
      <el-table-column prop="total_visits" label="到店次数" />
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { http } from '@/api/client'
import { formatDateTime } from '@/utils/format'

interface ChurnRisk {
  customer_id: string
  name: string
  churn_score: number
  last_visit_at: string | null
  total_visits: number
}

const items = ref<ChurnRisk[]>([])
const loading = ref(false)
const threshold = ref(0.5)

async function reload() {
  loading.value = true
  try {
    const { data } = await http.get<ChurnRisk[]>('/operations/churn', {
      params: { threshold: threshold.value }
    })
    items.value = data
  } finally { loading.value = false }
}

onMounted(reload)
</script>
