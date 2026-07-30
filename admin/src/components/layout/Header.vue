<template>
  <el-header class="header">
    <div class="header__left">
      <el-tooltip :content="app.sidebarCollapsed ? '展开导航' : '收起导航'" placement="bottom">
        <el-button class="header__icon-button" text circle @click="app.toggleSidebar">
          <el-icon><Fold v-if="!app.sidebarCollapsed" /><Expand v-else /></el-icon>
        </el-button>
      </el-tooltip>
      <GlobalSearch />
    </div>

    <div class="header__workspace" aria-label="当前工作区">
      <span class="header__workspace-mark"><el-icon><Grid /></el-icon></span>
      <span class="header__workspace-title">运营工作台</span>
      <span class="header__workspace-hint">门店经营一览</span>
    </div>

    <div class="header__actions">
      <el-tooltip content="经营大屏" placement="bottom">
        <el-button class="header__icon-button" text circle aria-label="打开经营大屏" @click="goBigscreen">
          <el-icon><Monitor /></el-icon>
        </el-button>
      </el-tooltip>
      <el-dropdown @command="onCommand">
        <button class="header__user" type="button">
          <el-avatar :size="30" class="header__avatar">{{ userInitial }}</el-avatar>
          <span class="header__username">{{ auth.username || '管理员' }}</span>
          <el-icon class="header__caret"><CaretBottom /></el-icon>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="logout">退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </el-header>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { CaretBottom, Expand, Fold, Grid, Monitor } from '@element-plus/icons-vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import GlobalSearch from './GlobalSearch.vue'

const router = useRouter()
const app = useAppStore()
const auth = useAuthStore()
const userInitial = computed(() => (auth.username || '管').trim().slice(0, 1).toUpperCase())

function goBigscreen() {
  window.open('/admin/bigscreen', '_blank', 'noopener')
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
.header { height: 60px; background: #fff; border-bottom: 1px solid #eaecf0; display: flex; align-items: center; gap: 20px; padding: 0 20px; box-shadow: 0 1px 2px rgb(16 24 40 / 2%); }
.header__left, .header__actions { display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
.header__workspace { min-width: 0; flex: 1; display: flex; align-items: center; gap: 8px; color: #344054; }
.header__workspace-mark { display: grid; width: 24px; height: 24px; place-items: center; border-radius: 7px; color: #9a6700; background: #fff7d6; }
.header__workspace-title { font-size: 14px; font-weight: 650; white-space: nowrap; }
.header__workspace-hint { color: #98a2b3; font-size: 12px; padding-left: 8px; border-left: 1px solid #eaecf0; white-space: nowrap; }
.header__icon-button { color: #475467; font-size: 18px; }
.header__icon-button:hover { color: #9a6700; background: #fff7d6; }
.header__user { border: 0; background: transparent; display: flex; align-items: center; gap: 8px; padding: 4px 6px; border-radius: 8px; cursor: pointer; color: #344054; font: inherit; }
.header__user:hover { background: #f9fafb; }
.header__avatar { color: #fff; background: linear-gradient(135deg, #334155, #475569); font-size: 12px; font-weight: 700; }
.header__username { max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; font-weight: 600; }
.header__caret { color: #98a2b3; font-size: 13px; }
@media (max-width: 900px) { .header { padding: 0 12px; gap: 10px; } .header__workspace-hint, .header__username { display: none; } }
</style>
