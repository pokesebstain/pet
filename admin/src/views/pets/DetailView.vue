<template>
  <div>
    <el-page-header @back="goBack" title="返回宠物列表" />
    <h2>宠物详情</h2>
    <el-descriptions v-if="pet" :column="2" border>
      <el-descriptions-item label="名字">{{ pet.name || '-' }}</el-descriptions-item>
      <el-descriptions-item label="物种">{{ profileValue(pet.species) }}</el-descriptions-item>
      <el-descriptions-item label="品种">{{ profileValue(pet.breed) }}</el-descriptions-item>
      <el-descriptions-item label="体重(kg)">{{ pet.weight_kg ?? '-' }}</el-descriptions-item>
      <el-descriptions-item label="生命阶段">{{ pet.life_stage || '-' }}</el-descriptions-item>
      <el-descriptions-item label="出生日期">{{ pet.birth_date || '-' }}</el-descriptions-item>
    </el-descriptions>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { petsApi, type Pet } from '@/api/pets'
import { petProfileValue } from '@/utils/pet-profile'

const route = useRoute()
const router = useRouter()
const pet = ref<Pet | null>(null)
const profileValue = petProfileValue

onMounted(async () => {
  pet.value = await petsApi.get(String(route.params.id))
})

function goBack() { router.push('/pets') }
</script>
