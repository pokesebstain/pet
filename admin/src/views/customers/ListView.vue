<template>
  <div>
    <h2>客户</h2>
    <DataTable
      :items="items"
      :total="total"
      :loading="loading"
      @page-change="(p) => { page = p; reload() }"
      @size-change="(s) => { pageSize = s; reload() }"
    >
      <template #toolbar>
        <el-input v-model="search" placeholder="搜索姓名/手机号" clearable style="width: 240px" @keyup.enter="reload" />
        <el-button @click="reload">搜索</el-button>
        <el-button type="primary" @click="openCreate">新建客户</el-button>
      </template>
      <el-table-column prop="name" label="姓名" />
      <el-table-column prop="phone" label="手机号" />
      <el-table-column prop="ltv" label="LTV" />
      <el-table-column prop="churn_score" label="流失概率" />
      <el-table-column prop="segment" label="分群" />
      <el-table-column label="操作" width="220">
        <template #default="{ row }">
          <el-button text type="primary" @click="goDetail(row.customer_id)">详情</el-button>
          <el-button text type="primary" @click="openEdit(row)">编辑</el-button>
          <el-popconfirm title="确认删除?" @confirm="onRemove(row.customer_id)">
            <template #reference><el-button text type="danger">删除</el-button></template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </DataTable>

    <FormDrawer
      v-model="drawerOpen"
      :title="editing ? '编辑客户' : '新建客户'"
      :form="form"
      @submit="onSubmit"
    >
      <template #default="{ form }">
        <el-form-item label="姓名" required>
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="form.phone" />
        </el-form-item>
      </template>
    </FormDrawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import DataTable from '@/components/common/DataTable.vue'
import FormDrawer from '@/components/common/FormDrawer.vue'
import { customersApi, type Customer } from '@/api/customers'

const route = useRoute()
const router = useRouter()
const items = ref<Customer[]>([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const search = ref('')
// 支持从仪表盘"今日待办"跳转时带 ?onboarding_pending=true 预筛选。
const onboardingPending = ref<boolean | undefined>(
  route.query.onboarding_pending === 'true' ? true : undefined
)
const drawerOpen = ref(false)
const editing = ref(false)
const editingId = ref<string | null>(null)
const form = reactive({ name: '', phone: '' })

async function reload() {
  loading.value = true
  try {
    const r = await customersApi.list(page.value, pageSize.value, search.value || undefined, onboardingPending.value)
    items.value = r.items
    total.value = r.total
  } finally { loading.value = false }
}

function openCreate() {
  editing.value = false
  editingId.value = null
  form.name = ''
  form.phone = ''
  drawerOpen.value = true
}

function openEdit(row: Customer) {
  editing.value = true
  editingId.value = row.customer_id
  form.name = row.name
  form.phone = row.phone ?? ''
  drawerOpen.value = true
}

async function onSubmit() {
  try {
    if (editing.value && editingId.value) {
      await customersApi.update(editingId.value, { name: form.name, phone: form.phone || undefined })
      ElMessage.success('已更新')
    } else {
      await customersApi.create({ name: form.name, phone: form.phone || undefined })
      ElMessage.success('已创建')
    }
    drawerOpen.value = false
    await reload()
  } catch (e) { /* interceptor 已 toast */ }
}

async function onRemove(id: string) {
  await customersApi.remove(id)
  ElMessage.success('已删除')
  await reload()
}

function goDetail(id: string) { router.push(`/customers/${id}`) }

onMounted(reload)
</script>
