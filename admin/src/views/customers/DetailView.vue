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

    <section class="pets-section">
      <div class="pets-section__header">
        <h3>名下宠物<span v-if="customer">（{{ customer.pet_count }}）</span></h3>
        <el-button type="primary" :disabled="!customer" @click="openCreatePet">新增宠物</el-button>
      </div>
      <el-table v-if="pets.length" v-loading="petsLoading" :data="pets" border>
        <el-table-column label="名字" min-width="120">
          <template #default="{ row }">{{ row.name || '待完善' }}</template>
        </el-table-column>
        <el-table-column label="物种" min-width="100">
          <template #default="{ row }">{{ profileValue(row.species) }}</template>
        </el-table-column>
        <el-table-column label="品种" min-width="120">
          <template #default="{ row }">{{ profileValue(row.breed) }}</template>
        </el-table-column>
        <el-table-column label="生命阶段" min-width="100">
          <template #default="{ row }">{{ row.life_stage || '待完善' }}</template>
        </el-table-column>
        <el-table-column label="资料状态" min-width="100">
          <template #default="{ row }">
            <el-tag :type="isPending(row) ? 'warning' : 'success'" size="small">
              {{ isPending(row) ? '待完善' : '已完善' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button text type="primary" @click="goPetDetail(row.pet_id)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else v-loading="petsLoading" description="暂无名下宠物，可新增宠物档案" :image-size="72" />
    </section>

    <FormDrawer
      v-model="petDrawerOpen"
      title="新增宠物"
      :form="petForm"
      @submit="onCreatePet"
    >
      <template #default="{ form }">
        <el-alert title="物种和品种可留空，保存后会标为“待完善”。" type="info" :closable="false" show-icon />
        <el-form-item label="名字">
          <el-input v-model="form.name" placeholder="例如：团团" />
        </el-form-item>
        <el-form-item label="物种">
          <el-input v-model="form.species" placeholder="可留空，待后续完善" />
        </el-form-item>
        <el-form-item label="品种">
          <el-input v-model="form.breed" placeholder="可留空，待后续完善" />
        </el-form-item>
      </template>
    </FormDrawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import FormDrawer from '@/components/common/FormDrawer.vue'
import { customersApi, type Customer } from '@/api/customers'
import { petsApi, type Pet } from '@/api/pets'
import { formatDateTime } from '@/utils/format'
import { isPetProfilePending, petProfileValue } from '@/utils/pet-profile'

const route = useRoute()
const router = useRouter()
const customer = ref<Customer | null>(null)
const pets = ref<Pet[]>([])
const petsLoading = ref(false)
const petDrawerOpen = ref(false)
const petForm = reactive({ name: '', species: '', breed: '' })
const profileValue = petProfileValue
const isPending = isPetProfilePending

async function reload() {
  const customerId = String(route.params.id)
  petsLoading.value = true
  try {
    const [customerResponse, petsResponse] = await Promise.all([
      customersApi.get(customerId),
      petsApi.list(1, 200, undefined, undefined, customerId)
    ])
    customer.value = customerResponse
    pets.value = petsResponse.items
  } finally {
    petsLoading.value = false
  }
}

function openCreatePet() {
  petForm.name = ''
  petForm.species = ''
  petForm.breed = ''
  petDrawerOpen.value = true
}

async function onCreatePet() {
  if (!customer.value) return
  try {
    await petsApi.create({
      owner_id: customer.value.customer_id,
      name: petForm.name || null,
      species: petForm.species || null,
      breed: petForm.breed || null
    })
    petDrawerOpen.value = false
    ElMessage.success('已新增宠物档案')
    await reload()
  } catch (error) {
    // 请求拦截器已展示失败提示。
  }
}

function goBack() { router.push('/customers') }
function goPetDetail(id: string) { router.push(`/pets/${id}`) }

onMounted(reload)
</script>

<style scoped>
.pets-section { margin-top: 24px; }
.pets-section__header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.pets-section__header h3 { margin: 0; }
</style>
