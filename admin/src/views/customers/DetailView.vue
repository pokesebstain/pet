<template>
  <div>
    <el-page-header @back="goBack" title="返回客户列表" />
    <h2>客户详情</h2>
    <el-descriptions v-if="customer" :column="2" border>
      <el-descriptions-item label="姓名">{{ customer.name }}</el-descriptions-item>
      <el-descriptions-item label="手机号">{{ customer.phone || '-' }}</el-descriptions-item>
      <el-descriptions-item label="LTV">{{ customer.ltv ?? '-' }}</el-descriptions-item>
      <el-descriptions-item label="流失概率">{{ customer.churn_score ?? '-' }}</el-descriptions-item>
      <el-descriptions-item label="分群">{{ customer.segment || '-' }}</el-descriptions-item>
      <el-descriptions-item label="注册时间">{{ formatDateTime(customer.registered_at) }}</el-descriptions-item>
    </el-descriptions>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { customersApi, type Customer } from '@/api/customers'
import { formatDateTime } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const customer = ref<Customer | null>(null)

onMounted(async () => {
  const id = String(route.params.id)
  customer.value = await customersApi.get(id)
})

function goBack() { router.push('/customers') }
</script>
