<template>
  <div>
    <h2>Agent 对话追溯</h2>
    <DataTable
      :items="items"
      :total="total"
      :loading="loading"
      @page-change="(p) => { page = p; reload() }"
      @size-change="(s) => { pageSize = s; reload() }"
    >
      <el-table-column prop="trace_id" label="Trace ID" />
      <el-table-column prop="thread_id" label="Thread" />
      <el-table-column prop="started_at" label="开始">
        <template #default="{ row }">{{ formatDateTime(row.started_at) }}</template>
      </el-table-column>
      <el-table-column prop="ended_at" label="结束">
        <template #default="{ row }">{{ row.ended_at ? formatDateTime(row.ended_at) : '-' }}</template>
      </el-table-column>
      <el-table-column prop="status" label="状态">
        <template #default="{ row }">
          <el-tag :type="row.status === 'completed' ? 'success' : 'warning'">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-button
            text
            type="primary"
            :disabled="!row.thread_id"
            @click="goDetail(row.thread_id)"
          >详情</el-button>
        </template>
      </el-table-column>
    </DataTable>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import DataTable from '@/components/common/DataTable.vue'
import { listPage } from '@/utils/http'
import { formatDateTime } from '@/utils/format'

interface Trace {
  trace_id: string
  thread_id: string
  started_at: string
  ended_at: string | null
  status: string
  final_answer: string | null
}

const items = ref<Trace[]>([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const router = useRouter()

async function reload() {
  loading.value = true
  try {
    const r = await listPage<Trace>('/traces', {
      page: page.value, page_size: pageSize.value
    })
    items.value = r.items
    total.value = r.total
  } finally { loading.value = false }
}

function goDetail(threadId: string) { router.push(`/traces/${threadId}`) }

onMounted(reload)
</script>
