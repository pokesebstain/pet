<template>
  <div>
    <h2>宠物</h2>
    <DataTable
      :items="items"
      :total="total"
      :loading="loading"
      @page-change="(p) => { page = p; reload() }"
      @size-change="(s) => { pageSize = s; reload() }"
    >
      <template #toolbar>
        <el-input v-model="search" placeholder="搜索名字/品种" clearable style="width: 240px" @keyup.enter="reload" />
        <el-button @click="reload">搜索</el-button>
      </template>
      <el-table-column prop="name" label="名字" />
      <el-table-column prop="species" label="物种" />
      <el-table-column prop="breed" label="品种" />
      <el-table-column prop="weight_kg" label="体重(kg)" />
      <el-table-column prop="life_stage" label="生命阶段" />
      <el-table-column prop="onboarding_pending" label="待完善">
        <template #default="{ row }">
          <el-tag v-if="row.onboarding_pending" type="warning" size="small">待完善</el-tag>
          <el-tag v-else type="success" size="small">已完善</el-tag>
        </template>
      </el-table-column>
    </DataTable>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import DataTable from '@/components/common/DataTable.vue'
import { petsApi, type Pet } from '@/api/pets'

const items = ref<Pet[]>([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const search = ref('')

async function reload() {
  loading.value = true
  try {
    const r = await petsApi.list(page.value, pageSize.value, search.value || undefined)
    items.value = r.items
    total.value = r.total
  } finally { loading.value = false }
}

onMounted(reload)
</script>
