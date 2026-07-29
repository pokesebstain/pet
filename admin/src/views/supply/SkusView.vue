<template>
  <div>
    <h2>SKU</h2>
    <DataTable
      :items="items"
      :total="total"
      :loading="loading"
      @page-change="(p) => { page = p; reload() }"
      @size-change="(s) => { pageSize = s; reload() }"
    >
      <template #toolbar>
        <el-input v-model="search" placeholder="搜索 SKU 名字" clearable style="width: 240px" @keyup.enter="reload" />
        <el-button @click="reload">搜索</el-button>
      </template>
      <el-table-column prop="sku_id" label="ID" />
      <el-table-column prop="name" label="名字" />
      <el-table-column prop="unit" label="单位" />
      <el-table-column prop="current_stock" label="当前库存" />
      <el-table-column prop="reorder_point" label="补货点" />
      <el-table-column prop="safety_stock" label="安全库存" />
      <el-table-column label="状态">
        <template #default="{ row }">
          <el-tag v-if="row.current_stock < row.safety_stock" type="danger">低库存</el-tag>
          <el-tag v-else-if="row.current_stock < row.reorder_point" type="warning">需补货</el-tag>
          <el-tag v-else type="success">充足</el-tag>
        </template>
      </el-table-column>
    </DataTable>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import DataTable from '@/components/common/DataTable.vue'
import { listPage } from '@/utils/http'

interface Sku {
  sku_id: string
  name: string
  unit: string
  current_stock: number
  reorder_point: number
  safety_stock: number
}

const items = ref<Sku[]>([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const search = ref('')

async function reload() {
  loading.value = true
  try {
    const r = await listPage<Sku>('/supply/skus', {
      page: page.value, page_size: pageSize.value, search: search.value || undefined
    })
    items.value = r.items
    total.value = r.total
  } finally { loading.value = false }
}

onMounted(reload)
</script>
