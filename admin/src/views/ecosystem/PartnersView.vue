<template>
  <div>
    <h2>合作医院 / 转诊</h2>
    <h3>合作医院</h3>
    <el-table :data="partners" v-loading="loadingPartners" border>
      <el-table-column prop="partner_id" label="ID" />
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="address" label="地址" />
      <el-table-column prop="phone" label="电话" />
      <el-table-column prop="specialties" label="擅长">
        <template #default="{ row }">
          <el-tag v-for="s in row.specialties" :key="s" size="small" style="margin-right: 4px">{{ s }}</el-tag>
        </template>
      </el-table-column>
    </el-table>

    <h3 style="margin-top: 24px">转诊记录</h3>
    <DataTable
      :items="referrals"
      :total="referralTotal"
      :loading="loadingReferrals"
      @page-change="(p) => { page = p; reloadReferrals() }"
      @size-change="(s) => { pageSize = s; reloadReferrals() }"
    >
      <el-table-column prop="referral_id" label="ID" />
      <el-table-column prop="customer_id" label="客户" />
      <el-table-column prop="pet_id" label="宠物" />
      <el-table-column prop="partner_id" label="医院" />
      <el-table-column prop="status" label="状态">
        <template #default="{ row }">
          <el-tag :type="row.status === 'completed' ? 'success' : 'warning'">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
    </DataTable>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import DataTable from '@/components/common/DataTable.vue'
import { http } from '@/api/client'
import { listPage } from '@/utils/http'
import { formatDateTime } from '@/utils/format'

interface Partner {
  partner_id: string
  name: string
  address: string
  phone: string
  specialties: string[]
}

interface Referral {
  referral_id: string
  customer_id: string
  pet_id: string
  partner_id: string
  status: string
  created_at: string
}

const partners = ref<Partner[]>([])
const loadingPartners = ref(false)

const referrals = ref<Referral[]>([])
const referralTotal = ref(0)
const loadingReferrals = ref(false)
const page = ref(1)
const pageSize = ref(20)

async function reloadPartners() {
  loadingPartners.value = true
  try {
    const { data } = await http.get<Partner[]>('/ecosystem/partners')
    partners.value = data
  } finally { loadingPartners.value = false }
}

async function reloadReferrals() {
  loadingReferrals.value = true
  try {
    const r = await listPage<Referral>('/ecosystem/referrals', {
      page: page.value, page_size: pageSize.value
    })
    referrals.value = r.items
    referralTotal.value = r.total
  } finally { loadingReferrals.value = false }
}

onMounted(() => {
  reloadPartners()
  reloadReferrals()
})
</script>
