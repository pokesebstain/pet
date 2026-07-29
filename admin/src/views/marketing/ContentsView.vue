<template>
  <div>
    <h2>营销内容</h2>
    <DataTable
      :items="items"
      :total="total"
      :loading="loading"
      @page-change="(p) => { page = p; reload() }"
      @size-change="(s) => { pageSize = s; reload() }"
    >
      <template #toolbar>
        <el-button type="primary" @click="drawerOpen = true">生成新内容</el-button>
      </template>
      <el-table-column prop="content_id" label="ID" />
      <el-table-column prop="topic" label="主题" />
      <el-table-column prop="channel" label="渠道" />
      <el-table-column prop="status" label="状态">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="generated_at" label="生成时间">
        <template #default="{ row }">{{ formatDateTime(row.generated_at) }}</template>
      </el-table-column>
    </DataTable>

    <FormDrawer v-model="drawerOpen" title="生成营销内容" :form="form" @submit="onSubmit">
      <template #default="{ form }">
        <el-form-item label="主题"><el-input v-model="form.topic" /></el-form-item>
        <el-form-item label="渠道">
          <el-select v-model="form.channel">
            <el-option v-for="c in channels" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
      </template>
    </FormDrawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import DataTable from '@/components/common/DataTable.vue'
import FormDrawer from '@/components/common/FormDrawer.vue'
import { listPage, createOne } from '@/utils/http'
import { formatDateTime } from '@/utils/format'

interface Content {
  content_id: string
  topic: string
  channel: string
  body_preview: string
  status: string
  generated_at: string
}

const items = ref<Content[]>([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const drawerOpen = ref(false)
const form = reactive({ topic: '', channel: 'wechat' })
const channels = ['wechat', 'sms', 'email']

function statusTagType(s: string): 'success' | 'warning' | 'info' {
  if (s === 'approved' || s === 'sent') return 'success'
  if (s === 'draft') return 'info'
  return 'warning'
}

async function reload() {
  loading.value = true
  try {
    const r = await listPage<Content>('/marketing/contents', {
      page: page.value, page_size: pageSize.value
    })
    items.value = r.items
    total.value = r.total
  } finally { loading.value = false }
}

async function onSubmit() {
  await createOne<Content>('/marketing/contents/generate', { ...form })
  ElMessage.success('已生成（draft）')
  drawerOpen.value = false
  form.topic = ''
  await reload()
}

onMounted(reload)
</script>
