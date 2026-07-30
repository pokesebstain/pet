<template>
  <div>
    <h2>预约</h2>
    <DataTable
      :items="items"
      :total="total"
      :loading="loading"
      @page-change="(p) => { page = p; reload() }"
      @size-change="(s) => { pageSize = s; reload() }"
    >
      <template #toolbar>
        <el-select v-model="statusFilter" placeholder="状态" clearable style="width: 140px" @change="reload">
          <el-option v-for="s in statuses" :key="s" :label="s" :value="s" />
        </el-select>
        <el-button @click="reload">刷新</el-button>
      </template>
      <el-table-column prop="appointment_id" label="ID" />
      <el-table-column prop="customer_id" label="客户" />
      <el-table-column prop="pet_id" label="宠物" />
      <el-table-column prop="service_type" label="服务" />
      <el-table-column prop="start_at" label="开始时间">
        <template #default="{ row }">{{ formatDateTime(row.start_at) }}</template>
      </el-table-column>
      <el-table-column prop="status" label="状态">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-popconfirm
            v-if="['pending', 'confirmed'].includes(row.status)"
            title="确认取消预约?"
            @confirm="onCancel(row.appointment_id)"
          >
            <template #reference><el-button text type="danger">取消</el-button></template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </DataTable>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import DataTable from '@/components/common/DataTable.vue'
import { appointmentsApi, type Appointment } from '@/api/appointments'
import { formatDateTime } from '@/utils/format'

const route = useRoute()
const items = ref<Appointment[]>([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
// 支持从仪表盘"今日待办"跳转时带 ?status=pending 预筛选。
const statusFilter = ref<string | null>((route.query.status as string) || null)
const statuses = ['pending', 'confirmed', 'completed', 'cancelled']

async function reload() {
  loading.value = true
  try {
    const r = await appointmentsApi.list(page.value, pageSize.value, {
      status: statusFilter.value || undefined
    })
    items.value = r.items
    total.value = r.total
  } finally { loading.value = false }
}

function statusTagType(s: string): 'success' | 'warning' | 'info' | 'danger' {
  if (s === 'confirmed') return 'success'
  if (s === 'cancelled') return 'danger'
  if (s === 'completed') return 'info'
  return 'warning'
}

async function onCancel(id: string) {
  await appointmentsApi.cancel(id)
  ElMessage.success('已取消')
  await reload()
}

onMounted(reload)
</script>
