<template>
  <nav class="page-tabs" aria-label="已打开页面">
    <div class="page-tabs__scroll">
      <div
        v-for="tab in app.tabs"
        :key="tab.path"
        class="page-tabs__item"
        :class="{ 'page-tabs__item--active': tab.path === app.activeTabPath }"
        role="tab"
        :aria-selected="tab.path === app.activeTabPath"
        :title="tab.title"
        tabindex="0"
        @click="activate(tab.path)"
        @keydown.enter="activate(tab.path)"
      >
        <span class="page-tabs__dot" />
        <span class="page-tabs__title">{{ tab.title }}</span>
        <button
          v-if="tab.closable"
          class="page-tabs__close"
          type="button"
          :aria-label="`关闭${tab.title}`"
          @click.stop="close(tab.path)"
        >
          <el-icon><Close /></el-icon>
        </button>
      </div>
    </div>
  </nav>
</template>

<script setup lang="ts">
import { Close } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'

const app = useAppStore()
const router = useRouter()

function activate(path: string) {
  if (path !== router.currentRoute.value.fullPath) router.push(path)
  app.setActiveTab(path)
}

function close(path: string) {
  const fallbackPath = app.closeTab(path)
  if (fallbackPath) router.push(fallbackPath)
}
</script>

<style scoped>
.page-tabs {
  height: 42px;
  display: flex;
  align-items: end;
  flex-shrink: 0;
  background: #fff;
  border-bottom: 1px solid #eaecf0;
  padding: 0 20px;
}
.page-tabs__scroll {
  display: flex;
  align-items: stretch;
  gap: 4px;
  width: 100%;
  height: 42px;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: thin;
}
.page-tabs__item {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-width: 104px;
  max-width: 180px;
  border: 0;
  border-radius: 8px 8px 0 0;
  padding: 0 10px 0 12px;
  background: transparent;
  color: #667085;
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  transition: color .16s ease, background .16s ease;
}
.page-tabs__item:hover { background: #f9fafb; color: #344054; }
.page-tabs__item--active { background: #fff8e1; color: #8b5e00; font-weight: 650; }
.page-tabs__item--active::after { content: ''; position: absolute; right: 10px; bottom: 0; left: 10px; height: 2px; border-radius: 2px 2px 0 0; background: #eaaa08; }
.page-tabs__dot { width: 6px; height: 6px; flex: 0 0 auto; border-radius: 50%; background: #d0d5dd; }
.page-tabs__item--active .page-tabs__dot { background: #eaaa08; box-shadow: 0 0 0 3px rgb(234 170 8 / 16%); }
.page-tabs__title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.page-tabs__close { display: inline-grid; width: 18px; height: 18px; flex: 0 0 auto; place-items: center; margin-left: auto; padding: 0; border: 0; border-radius: 5px; background: transparent; color: #98a2b3; cursor: pointer; font-size: 13px; }
.page-tabs__close:hover, .page-tabs__close:focus-visible { background: rgb(16 24 40 / 8%); color: #344054; outline: none; }
@media (max-width: 900px) { .page-tabs { padding: 0 12px; } .page-tabs__item { min-width: 92px; } }
</style>
