<template>
  <div class="bigscreen">
    <header class="bigscreen__header">
      <h1 class="bigscreen__title">PetOps 实时大屏</h1>
      <div class="bigscreen__clock">{{ now }}</div>
    </header>

    <section class="bigscreen__stats">
      <div class="stat" v-for="s in stats" :key="s.key">
        <div class="stat__label">{{ s.label }}</div>
        <div class="stat__value" :data-value="s.value">
          <span class="stat__num">{{ s.display }}</span>
          <span class="stat__unit" v-if="s.unit">{{ s.unit }}</span>
        </div>
      </div>
    </section>

    <section class="bigscreen__charts">
      <div class="chart-card">
        <h3 class="chart-card__title">服务分布</h3>
        <div ref="serviceChartEl" class="chart-card__chart"></div>
        <div v-if="!data" class="chart-card__empty">暂无数据</div>
      </div>
      <div class="chart-card">
        <h3 class="chart-card__title">热门宠物 TOP 5</h3>
        <ul class="top-pets">
          <li v-for="(p, i) in data?.top_pets || []" :key="p.name">
            <span class="top-pets__rank" :data-rank="i + 1">{{ i + 1 }}</span>
            <span class="top-pets__name">{{ p.name }}</span>
            <span class="top-pets__visits">{{ p.visits }} 次</span>
          </li>
          <li v-if="!data?.top_pets?.length" class="top-pets__empty">暂无数据</li>
        </ul>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import * as echarts from 'echarts/core'
import { PieChart, BarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { http } from '@/api/client'

echarts.use([PieChart, BarChart, TitleComponent, TooltipComponent, LegendComponent, CanvasRenderer])

interface BigscreenData {
  today_appointments: number
  today_new_customers: number
  month_revenue: number
  pending_alerts: number
  low_stock_skus: number
  service_distribution: Record<string, number>
  top_pets: Array<{ name: string; visits: number }>
  generated_at: string
}

const data = ref<BigscreenData | null>(null)
const now = ref('')
const serviceChartEl = ref<HTMLDivElement | null>(null)
let serviceChart: echarts.ECharts | null = null
let pollTimer: number | null = null
let clockTimer: number | null = null

const stats = computed(() => [
  { key: 'appts', label: '今日预约', value: data.value?.today_appointments ?? 0, display: String(data.value?.today_appointments ?? 0), unit: '' },
  { key: 'cust', label: '今日新客', value: data.value?.today_new_customers ?? 0, display: String(data.value?.today_new_customers ?? 0), unit: '' },
  { key: 'rev', label: '本月营收', value: data.value?.month_revenue ?? 0, display: formatYuan(data.value?.month_revenue ?? 0), unit: '元' },
  { key: 'alert', label: '待处理告警', value: data.value?.pending_alerts ?? 0, display: String(data.value?.pending_alerts ?? 0), unit: '' },
  { key: 'low', label: '低库存 SKU', value: data.value?.low_stock_skus ?? 0, display: String(data.value?.low_stock_skus ?? 0), unit: '' }
])

function formatYuan(v: number): string {
  if (v >= 10000) return (v / 10000).toFixed(1) + 'w'
  if (v >= 1000) return (v / 1000).toFixed(1) + 'k'
  return v.toFixed(0)
}

async function fetchData() {
  try {
    const r = await http.get<BigscreenData>('/stats/bigscreen')
    data.value = r.data
    renderServiceChart()
  } catch (e) { /* interceptor 已 toast */ }
}

function renderServiceChart() {
  if (!serviceChartEl.value || !data.value) return
  const dist = data.value.service_distribution || {}
  const entries = Object.entries(dist).map(([name, value]) => ({ name, value }))
  if (!serviceChart) {
    serviceChart = echarts.init(serviceChartEl.value)
  }
  serviceChart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'item', formatter: '{b}: {c}%' },
    legend: { textStyle: { color: '#9bb0d3' }, bottom: 0 },
    series: [
      {
        type: 'pie',
        radius: ['38%', '68%'],
        center: ['50%', '45%'],
        label: { color: '#e6f1ff', fontSize: 14 },
        itemStyle: {
          borderColor: '#0a0e27',
          borderWidth: 2
        },
        data: entries,
        color: ['#00f2ff', '#3a7bd5', '#9b59ff', '#27e8a7', '#ffc857']
      }
    ]
  })
}

function updateClock() {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  const weekDays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
  now.value = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${weekDays[d.getDay()]} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function startPolling() {
  updateClock()
  fetchData()
  clockTimer = window.setInterval(updateClock, 1000)
  pollTimer = window.setInterval(fetchData, 30000) // 30 秒
}

function stopPolling() {
  if (clockTimer) { window.clearInterval(clockTimer); clockTimer = null }
  if (pollTimer) { window.clearInterval(pollTimer); pollTimer = null }
  if (serviceChart) { serviceChart.dispose(); serviceChart = null }
}

onMounted(() => {
  startPolling()
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  stopPolling()
  window.removeEventListener('resize', onResize)
})

function onResize() {
  serviceChart?.resize()
}
</script>

<style scoped>
.bigscreen {
  min-height: 100vh;
  background: linear-gradient(135deg, #0a0e27 0%, #16213e 50%, #0f3460 100%);
  color: #e6f1ff;
  padding: 24px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

.bigscreen__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid rgba(0, 242, 255, 0.2);
}
.bigscreen__title {
  margin: 0;
  font-size: 32px;
  font-weight: 600;
  background: linear-gradient(90deg, #00f2ff 0%, #3a7bd5 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.bigscreen__clock {
  font-size: 18px;
  color: #9bb0d3;
  font-family: 'Courier New', monospace;
}

.bigscreen__stats {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}
.stat {
  background: linear-gradient(135deg, rgba(58, 123, 213, 0.2) 0%, rgba(0, 242, 255, 0.1) 100%);
  border: 1px solid rgba(0, 242, 255, 0.3);
  border-radius: 8px;
  padding: 20px;
  text-align: center;
}
.stat__label {
  font-size: 14px;
  color: #9bb0d3;
  margin-bottom: 8px;
}
.stat__value {
  font-size: 48px;
  font-weight: 700;
  background: linear-gradient(90deg, #00f2ff 0%, #27e8a7 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  line-height: 1.1;
}
.stat__num { font-size: 48px; }
.stat__unit {
  font-size: 18px;
  margin-left: 6px;
  color: #9bb0d3;
  -webkit-text-fill-color: #9bb0d3;
}

.bigscreen__charts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.chart-card {
  background: rgba(15, 52, 96, 0.4);
  border: 1px solid rgba(0, 242, 255, 0.2);
  border-radius: 8px;
  padding: 20px;
  min-height: 360px;
}
.chart-card__title {
  margin: 0 0 16px;
  font-size: 18px;
  color: #00f2ff;
  border-left: 3px solid #00f2ff;
  padding-left: 12px;
}
.chart-card__chart {
  height: 300px;
  position: relative;
}
.chart-card__empty {
  text-align: center;
  color: #9bb0d3;
  padding: 80px 0;
}

.top-pets {
  list-style: none;
  margin: 0;
  padding: 0;
}
.top-pets li {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 0;
  border-bottom: 1px solid rgba(155, 176, 211, 0.15);
  font-size: 16px;
}
.top-pets li:last-child { border-bottom: none; }
.top-pets__rank {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  background: rgba(0, 242, 255, 0.2);
  color: #00f2ff;
}
.top-pets__rank[data-rank="1"] { background: linear-gradient(135deg, #ffc857 0%, #ff8c00 100%); color: #fff; }
.top-pets__rank[data-rank="2"] { background: linear-gradient(135deg, #c0c0c0 0%, #808080 100%); color: #fff; }
.top-pets__rank[data-rank="3"] { background: linear-gradient(135deg, #cd7f32 0%, #8b4513 100%); color: #fff; }
.top-pets__name { flex: 1; font-size: 18px; }
.top-pets__visits {
  color: #27e8a7;
  font-weight: 600;
  font-size: 20px;
}
.top-pets__empty {
  text-align: center;
  color: #9bb0d3;
  padding: 60px 0;
  border: none !important;
}
</style>
