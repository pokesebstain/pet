<template>
  <el-header class="header">
    <el-button text @click="app.toggleSidebar">
      <el-icon><Fold v-if="!app.sidebarCollapsed" /><Expand v-else /></el-icon>
    </el-button>
    <span class="header__title">PetOps Admin</span>
    <div class="header__spacer" />
    <el-button text @click="goBigscreen" title="大屏">
      <el-icon><Monitor /></el-icon>
    </el-button>
    <el-dropdown @command="onCommand">
      <span class="header__user">
        <el-icon><UserFilled /></el-icon>
        {{ auth.username || 'admin' }}
        <el-icon><CaretBottom /></el-icon>
      </span>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item command="logout">退出登录</el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </el-header>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const app = useAppStore()
const auth = useAuthStore()

function goBigscreen() {
  window.open('/admin/bigscreen', '_blank')
}

function onCommand(cmd: string) {
  if (cmd === 'logout') {
    auth.clear()
    ElMessage.info('已退出登录')
    router.push('/login')
  }
}
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
.header__spacer { flex: 1; }
.header__user {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  color: #606266;
}
</style>
