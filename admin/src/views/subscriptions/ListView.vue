<template>
  <div>
    <h2>订阅</h2>
    <DataTable
      :items="items"
      :total="total"
      :loading="loading"
      @page-change="(p) => { page = p; reload() }"
      @size-change="(s) => { pageSize = s; reload() }"
    >
      <el-table-column prop="subscription_id" label="ID" />
      <el-table-column prop="customer_id" label="客户" />
      <el-table-column prop="plan_id" label="套餐" />
      <el-table-column prop="status" label="状态">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="started_at" label="开始">
        <template #default="{ row }">{{ formatDateTime(row.started_at) }}</template>
      </el-table-column>
      <el-table-column prop="next_billing_at" label="下次扣费">
        <template #default="{ row }">{{ row.next_billing_at ? formatDateTime(row.next_billing_at) : '-' }}</template>
      </el-table-column>
    </DataTable>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import DataTable from '@/components/common/DataTable.vue'
import { listPage } from '@/utils/http'
import { formatDateTime } from '@/utils/format'

interface Subscription {
  subscription_id: string
  customer_id: string
  plan_id: string
  status: string
  started_at: string
  next_billing_at: string | null
}

const items = ref<Subscription[]>([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)

async function reload() {
  loading.value = true
  try {
    const r = await listPage<Subscription>('/subscriptions', {
      page: page.value, page_size: pageSize.value
    })
    items.value = r.items
    total.value = r.total
  } finally { loading.value = false }
}

onMounted(reload)
</script>
