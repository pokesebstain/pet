<template>
  <el-card shadow="hover" class="stat-card" @click="$emit('click')">
    <div class="stat-card__top">
      <div>
        <div class="stat-card__label">{{ label }}</div>
        <div class="stat-card__value">{{ value }}</div>
      </div>
      <div v-if="sparkline && sparkline.length" ref="chartEl" class="stat-card__spark" />
    </div>
    <div class="stat-card__trend" v-if="trend !== undefined">
      <span :class="trend >= 0 ? 'up' : 'down'">
        {{ trend >= 0 ? '↑' : '↓' }} {{ Math.abs(trend) }}%
      </span>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, ref, watch, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, CanvasRenderer])

interface Props {
  label: string
  value: number | string
  trend?: number
  sparkline?: number[]
  color?: string
}
const props = defineProps<Props>()
defineEmits<{ (e: 'click'): void }>()

const chartEl = ref<HTMLDivElement>()
let chart: echarts.ECharts | undefined

function render() {
  if (!chartEl.value || !props.sparkline || !props.sparkline.length) return
  if (!chart) chart = echarts.init(chartEl.value)
  chart.setOption({
    grid: { left: 0, right: 0, top: 4, bottom: 0 },
    xAxis: { type: 'category', show: false, data: props.sparkline.map((_, i) => i) },
    yAxis: { type: 'value', show: false },
    series: [
      {
        type: 'line',
        data: props.sparkline,
        smooth: true,
        symbol: 'none',
        lineStyle: { color: props.color || '#f2b90c', width: 2 },
        areaStyle: { color: props.color || '#f2b90c', opacity: 0.12 }
      }
    ]
  })
  chart.resize()
}

onMounted(() => nextTick(render))
watch(() => props.sparkline, () => nextTick(render))
</script>

<style scoped>
.stat-card { margin-bottom: 12px; cursor: pointer; }
.stat-card__top { display: flex; justify-content: space-between; align-items: flex-start; }
.stat-card__label { color: #909399; font-size: 13px; }
.stat-card__value { font-size: 28px; font-weight: 600; margin: 8px 0; }
.stat-card__spark { width: 90px; height: 40px; }
.stat-card__trend .up { color: #67c23a; }
.stat-card__trend .down { color: #f56c6c; }
</style>
