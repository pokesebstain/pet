<template>
  <div>
    <h2>健康指标</h2>
    <DataTable
      :items="items"
      :total="total"
      :loading="loading"
      @page-change="(p) => { page = p; reload() }"
      @size-change="(s) => { pageSize = s; reload() }"
    >
      <template #toolbar>
        <el-input v-model="petId" placeholder="按宠物 ID 过滤" clearable style="width: 200px" @keyup.enter="reload" />
        <el-button @click="reload">过滤</el-button>
      </template>
      <el-table-column prop="metric_id" label="ID" />
      <el-table-column prop="pet_id" label="宠物" />
      <el-table-column prop="metric_type" label="指标" />
      <el-table-column prop="value" label="值" />
      <el-table-column prop="recorded_at" label="时间">
        <template #default="{ row }">{{ formatDateTime(row.recorded_at) }}</template>
      </el-table-column>
      <el-table-column prop="source" label="来源" />
    </DataTable>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import DataTable from '@/components/common/DataTable.vue'
import { http } from '@/api/client'
import { formatDateTime } from '@/utils/format'
import { listPage } from '@/utils/http'

interface Metric {
  metric_id: string
  pet_id: string
  metric_type: string
  value: number
  recorded_at: string
  source: string | null
}

const items = ref<Metric[]>([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const petId = ref('')

async function reload() {
  loading.value = true
  try {
    const r = await listPage<Metric>('/health/metrics', {
      page: page.value, page_size: pageSize.value, pet_id: petId.value || undefined
    })
    items.value = r.items
    total.value = r.total
  } finally { loading.value = false }
}

onMounted(reload)
</script>
