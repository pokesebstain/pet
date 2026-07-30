<template>
  <div class="data-table">
    <div class="data-table__toolbar" v-if="$slots.toolbar">
      <slot name="toolbar" />
    </div>
    <el-table :data="items" v-loading="loading" stripe border style="width: 100%">
      <slot />
    </el-table>
    <el-pagination
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :total="total"
      :page-sizes="[10, 20, 50, 100]"
      layout="total, sizes, prev, pager, next, jumper"
      @current-change="$emit('page-change', page)"
      @size-change="$emit('size-change', pageSize)"
    />
  </div>
</template>

<script setup lang="ts" generic="T extends Record<string, unknown>">
import { ref, watch } from 'vue'

interface Props {
  items: T[]
  total: number
  loading?: boolean
  initialPage?: number
  initialPageSize?: number
}
const props = withDefaults(defineProps<Props>(), {
  loading: false,
  initialPage: 1,
  initialPageSize: 20
})
defineEmits<{
  (e: 'page-change', page: number): void
  (e: 'size-change', size: number): void
}>()

const page = ref(props.initialPage)
const pageSize = ref(props.initialPageSize)
watch(() => props.initialPage, (v) => { page.value = v })
</script>

<style scoped>
.data-table {
  width: 100%;
  min-width: 0;
  max-width: 100%;
  overflow-x: auto;
}
.data-table :deep(.el-table) {
  width: 100%;
  max-width: 100%;
}
.data-table__toolbar {
  margin-bottom: 12px;
  display: flex;
  gap: 8px;
  align-items: center;
}
.el-pagination {
  margin-top: 12px;
  justify-content: flex-end;
  flex-wrap: wrap;
  row-gap: 8px;
}
</style>
