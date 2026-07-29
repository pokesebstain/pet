<template>
  <div>
    <h2>美容资源</h2>
    <el-alert type="info" :closable="false" style="margin-bottom: 12px">
      资源是配置类（美容师/设备）；只能修改名称 / 容量 / 启用状态。
    </el-alert>
    <el-table :data="items" v-loading="loading" border>
      <el-table-column prop="resource_id" label="ID" />
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="capacity" label="容量" />
      <el-table-column prop="is_active" label="启用">
        <template #default="{ row }">
          <el-tag v-if="row.is_active" type="success">启用</el-tag>
          <el-tag v-else type="info">停用</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-button text type="primary" @click="openEdit(row)">编辑</el-button>
        </template>
      </el-table-column>
    </el-table>

    <FormDrawer v-model="drawerOpen" title="编辑资源" :form="form" @submit="onSubmit">
      <template #default="{ form }">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="容量"><el-input-number v-model="form.capacity" :min="1" /></el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_active" />
        </el-form-item>
      </template>
    </FormDrawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { http } from '@/api/client'
import FormDrawer from '@/components/common/FormDrawer.vue'

interface Resource {
  resource_id: string
  name: string
  capacity: number
  is_active: boolean
}

const items = ref<Resource[]>([])
const loading = ref(false)
const drawerOpen = ref(false)
const form = reactive({ name: '', capacity: 1, is_active: true })
const editingId = ref<string | null>(null)

async function reload() {
  loading.value = true
  try {
    const { data } = await http.get<Resource[]>('/resources')
    items.value = data
  } finally { loading.value = false }
}

function openEdit(row: Resource) {
  editingId.value = row.resource_id
  form.name = row.name
  form.capacity = row.capacity
  form.is_active = row.is_active
  drawerOpen.value = true
}

async function onSubmit() {
  await http.put(`/resources/${editingId.value}`, { ...form })
  ElMessage.success('已保存')
  drawerOpen.value = false
  await reload()
}

onMounted(reload)
</script>
