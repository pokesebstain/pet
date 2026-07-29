<template>
  <div>
    <h2>健康告警</h2>
    <el-table :data="items" v-loading="loading" border>
      <el-table-column prop="alert_id" label="ID" />
      <el-table-column prop="pet_id" label="宠物" />
      <el-table-column prop="level" label="等级">
        <template #default="{ row }">
          <el-tag :type="levelTagType(row.level)">{{ row.level }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="title" label="标题" />
      <el-table-column prop="message" label="详情" />
      <el-table-column prop="created_at" label="创建时间">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column prop="acked_at" label="确认时间">
        <template #default="{ row }">{{ row.acked_at ? formatDateTime(row.acked_at) : '-' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-button
            v-if="!row.acked_at"
            text
            type="primary"
            @click="onAck(row.alert_id)"
          >确认</el-button>
          <el-tag v-else type="info" size="small">已确认</el-tag>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { http } from '@/api/client'
import { formatDateTime } from '@/utils/format'

interface Alert {
  alert_id: string
  pet_id: string
  level: string
  title: string
  message: string
  created_at: string
  acked_at: string | null
}

const items = ref<Alert[]>([])
const loading = ref(false)

async function reload() {
  loading.value = true
  try {
    const { data } = await http.get<Alert[]>('/health/alerts')
    items.value = data
  } finally { loading.value = false }
}

function levelTagType(s: string): 'success' | 'warning' | 'danger' {
  if (s === 'critical') return 'danger'
  if (s === 'warn') return 'warning'
  return 'success'
}

async function onAck(id: string) {
  await http.post(`/health/alerts/${id}/ack`)
  ElMessage.success('已确认')
  await reload()
}

onMounted(reload)
</script>
