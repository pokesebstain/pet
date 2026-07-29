<template>
  <div>
    <h2>LTV 分群</h2>
    <el-row :gutter="12">
      <el-col v-for="seg in items" :key="seg.segment" :span="6">
        <StatCard
          :label="seg.segment"
          :value="seg.customer_count"
          :trend="undefined"
        />
        <el-card shadow="never" style="margin-top: 8px">
          <div>平均 LTV: ¥{{ seg.avg_ltv.toFixed(2) }}</div>
          <div>总 LTV: ¥{{ seg.total_ltv.toFixed(2) }}</div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { http } from '@/api/client'
import StatCard from '@/components/common/StatCard.vue'

interface Segment {
  segment: string
  customer_count: number
  avg_ltv: number
  total_ltv: number
}

const items = ref<Segment[]>([])

onMounted(async () => {
  const { data } = await http.get<Segment[]>('/operations/ltv')
  items.value = data
})
</script>
