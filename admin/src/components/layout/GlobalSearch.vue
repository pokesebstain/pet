<template>
  <el-select
    v-model="keyword"
    filterable
    remote
    clearable
    reserve-keyword
    placeholder="搜索会员姓名 / 手机号 / 宠物名"
    :remote-method="onSearch"
    :loading="loading"
    class="global-search"
    no-match-text="未找到匹配的会员"
    @change="onSelect"
  >
    <el-option-group v-if="customerOptions.length" label="会员">
      <el-option
        v-for="c in customerOptions"
        :key="'c:' + c.customer_id"
        :value="'c:' + c.customer_id"
        :label="c.name"
      >
        <div class="global-search__row">
          <span class="global-search__name">{{ c.name }}</span>
          <span class="global-search__meta">{{ c.phone || '未登记手机号' }}</span>
        </div>
      </el-option>
    </el-option-group>
    <el-option-group v-if="petOptions.length" label="宠物">
      <el-option
        v-for="p in petOptions"
        :key="'p:' + p.pet_id"
        :value="'p:' + p.pet_id"
        :label="p.name || '未命名'"
      >
        <div class="global-search__row">
          <span class="global-search__name">{{ p.name || '未命名' }}</span>
          <span class="global-search__meta">{{ speciesLabel(p.species) }} · {{ p.breed }}</span>
        </div>
      </el-option>
    </el-option-group>
  </el-select>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { customersApi, type Customer } from '@/api/customers'
import { petsApi, type Pet } from '@/api/pets'

const router = useRouter()
const keyword = ref('')
const loading = ref(false)
const customerOptions = ref<Customer[]>([])
const petOptions = ref<Pet[]>([])

function speciesLabel(species: string): string {
  const map: Record<string, string> = { dog: '狗', cat: '猫', unknown: '待完善' }
  return map[species] || species
}

let debounceTimer: ReturnType<typeof setTimeout> | undefined

async function onSearch(query: string) {
  if (!query || !query.trim()) {
    customerOptions.value = []
    petOptions.value = []
    return
  }
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(async () => {
    loading.value = true
    try {
      const [customersRes, petsRes] = await Promise.all([
        customersApi.list(1, 8, query),
        petsApi.list(1, 8, query)
      ])
      customerOptions.value = customersRes.items
      petOptions.value = petsRes.items
    } finally {
      loading.value = false
    }
  }, 300)
}

function onSelect(value: string) {
  if (!value) return
  const [type, id] = value.split(':')
  keyword.value = ''
  customerOptions.value = []
  petOptions.value = []
  if (type === 'c') {
    router.push(`/customers/${id}`)
  } else if (type === 'p') {
    router.push(`/pets/${id}`)
  }
}
</script>

<style scoped>
.global-search { width: 320px; }
.global-search__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.global-search__name { font-weight: 500; }
.global-search__meta { color: #909399; font-size: 12px; }
</style>
