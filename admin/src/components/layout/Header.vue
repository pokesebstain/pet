<template>
  <el-header class="header">
    <el-button text @click="app.toggleSidebar">
      <el-icon><Fold v-if="!app.sidebarCollapsed" /><Expand v-else /></el-icon>
    </el-button>
    <span class="header__title">PetOps Admin</span>
  </el-header>
</template>

<script setup lang="ts">
import { useAppStore } from '@/stores/app'
const app = useAppStore()
</script>

<style scoped>
.header {
  background: #fff;
  border-bottom: 1px solid #e6e6e6;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 16px;
}
.header__title { font-size: 16px; font-weight: 600; }
</style>
