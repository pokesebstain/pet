<template>
  <div>
    <el-page-header @back="goBack" title="返回追溯列表" />
    <h2>对话追溯详情</h2>
    <el-descriptions :column="2" border>
      <el-descriptions-item label="Trace ID">{{ trace?.trace_id }}</el-descriptions-item>
      <el-descriptions-item label="Thread">{{ trace?.thread_id }}</el-descriptions-item>
      <el-descriptions-item label="开始">{{ formatDateTime(trace?.started_at) }}</el-descriptions-item>
      <el-descriptions-item label="结束">{{ trace?.ended_at ? formatDateTime(trace.ended_at) : '-' }}</el-descriptions-item>
      <el-descriptions-item label="状态">{{ trace?.status }}</el-descriptions-item>
      <el-descriptions-item label="回复" :span="2">{{ trace?.final_answer || '-' }}</el-descriptions-item>
    </el-descriptions>
    <h3 style="margin-top: 24px">节点步骤</h3>
    <el-table :data="trace?.steps || []" border>
      <el-table-column prop="event" label="事件" />
      <el-table-column prop="value" label="值" />
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { http } from '@/api/client'
import { formatDateTime } from '@/utils/format'

interface Step {
  event: string
  value: string
}

interface TraceDetail {
  trace_id: string
  thread_id: string
  started_at: string
  ended_at: string | null
  status: string
  final_answer: string | null
  steps: Step[]
}

const route = useRoute()
const router = useRouter()
const trace = ref<TraceDetail | null>(null)

onMounted(async () => {
  try {
    const { data } = await http.get<TraceDetail>(`/traces/${route.params.thread_id}`)
    trace.value = data
  } catch (e) { /* interceptor 已 toast */ }
})

function goBack() { router.push('/traces') }
</script>
