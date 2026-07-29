<template>
  <div>
    <h2>营业时间</h2>
    <el-alert type="info" :closable="false" style="margin-bottom: 12px">
      营业时间是配置类资源；只能修改已有星期的开放时间，不能新增/删除。
    </el-alert>
    <el-table :data="items" v-loading="loading" border>
      <el-table-column prop="weekday" label="星期" :formatter="weekdayLabel" />
      <el-table-column prop="open_time" label="开门" />
      <el-table-column prop="close_time" label="关门" />
      <el-table-column prop="is_closed" label="是否休息">
        <template #default="{ row }">
          <el-tag v-if="row.is_closed" type="info">休息</el-tag>
          <el-tag v-else type="success">营业</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-button text type="primary" @click="openEdit(row)">编辑</el-button>
        </template>
      </el-table-column>
    </el-table>

    <FormDrawer
      v-model="drawerOpen"
      title="编辑营业时间"
      :form="form"
      @submit="onSubmit"
    >
      <template #default="{ form }">
        <el-form-item label="开门时间 (HH:MM)">
          <el-input v-model="form.open_time" placeholder="09:00" />
        </el-form-item>
        <el-form-item label="关门时间 (HH:MM)">
          <el-input v-model="form.close_time" placeholder="19:00" />
        </el-form-item>
        <el-form-item label="是否休息">
          <el-switch v-model="form.is_closed" />
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

interface BusinessHour {
  weekday: number
  open_time: string
  close_time: string
  is_closed: boolean
}

const items = ref<BusinessHour[]>([])
const loading = ref(false)
const drawerOpen = ref(false)
const form = reactive({ open_time: '', close_time: '', is_closed: false })
const editingWeekday = ref<number | null>(null)

const WEEKDAY_LABELS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

function weekdayLabel(_row: any, _col: any, val: number): string {
  return WEEKDAY_LABELS[val] || `星期${val}`
}

async function reload() {
  loading.value = true
  try {
    const { data } = await http.get<BusinessHour[]>('/business-hours')
    items.value = data
  } finally { loading.value = false }
}

function openEdit(row: BusinessHour) {
  editingWeekday.value = row.weekday
  form.open_time = row.open_time
  form.close_time = row.close_time
  form.is_closed = row.is_closed
  drawerOpen.value = true
}

async function onSubmit() {
  await http.put(`/business-hours/${editingWeekday.value}`, {
    open_time: form.open_time,
    close_time: form.close_time,
    is_closed: form.is_closed
  })
  ElMessage.success('已保存')
  drawerOpen.value = false
  await reload()
}

onMounted(reload)
</script>
