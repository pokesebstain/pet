<template>
  <el-card shadow="hover" class="stat-card">
    <div class="stat-card__label">{{ label }}</div>
    <div class="stat-card__value">{{ value }}</div>
    <div class="stat-card__trend" v-if="trend !== undefined">
      <span :class="trend >= 0 ? 'up' : 'down'">
        {{ trend >= 0 ? '↑' : '↓' }} {{ Math.abs(trend) }}%
      </span>
    </div>
  </el-card>
</template>

<script setup lang="ts">
interface Props {
  label: string
  value: number | string
  trend?: number
}
defineProps<Props>()
</script>

<style scoped>
.stat-card { margin-bottom: 12px; }
.stat-card__label { color: #909399; font-size: 13px; }
.stat-card__value { font-size: 28px; font-weight: 600; margin: 8px 0; }
.stat-card__trend .up { color: #67c23a; }
.stat-card__trend .down { color: #f56c6c; }
</style>
