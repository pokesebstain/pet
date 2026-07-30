<template>
  <el-card shadow="hover" class="todo-panel">
    <template #header>
      <span class="todo-panel__title">今日待办</span>
    </template>
    <el-row :gutter="12">
      <el-col v-for="t in todos" :key="t.key" :span="6">
        <div class="todo-panel__item" @click="onClick(t)">
          <div class="todo-panel__count" :class="{ 'todo-panel__count--zero': t.count === 0 }">
            {{ t.count }}
          </div>
          <div class="todo-panel__label">{{ t.label }}</div>
        </div>
      </el-col>
    </el-row>
  </el-card>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import type { Todo } from '@/api/dashboard'

defineProps<{ todos: Todo[] }>()
const router = useRouter()

function onClick(t: Todo) {
  router.push(t.link)
}
</script>

<style scoped>
.todo-panel { margin-bottom: 16px; }
.todo-panel__title { font-weight: 600; }
.todo-panel__item {
  text-align: center;
  padding: 12px 4px;
  cursor: pointer;
  border-radius: 6px;
  transition: background 0.2s;
}
.todo-panel__item:hover { background: #f5f7fa; }
.todo-panel__count { font-size: 24px; font-weight: 700; color: #e6a23c; }
.todo-panel__count--zero { color: #c0c4cc; }
.todo-panel__label { color: #606266; font-size: 13px; margin-top: 4px; }
</style>
