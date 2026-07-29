import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import * as echarts from 'echarts/core';
import { PieChart, BarChart } from 'echarts/charts';
import { TitleComponent, TooltipComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { http } from '@/api/client';
echarts.use([PieChart, BarChart, TitleComponent, TooltipComponent, LegendComponent, CanvasRenderer]);
const data = ref(null);
const now = ref('');
const serviceChartEl = ref(null);
let serviceChart = null;
let pollTimer = null;
let clockTimer = null;
const stats = computed(() => [
    { key: 'appts', label: '今日预约', value: data.value?.today_appointments ?? 0, display: String(data.value?.today_appointments ?? 0), unit: '' },
    { key: 'cust', label: '今日新客', value: data.value?.today_new_customers ?? 0, display: String(data.value?.today_new_customers ?? 0), unit: '' },
    { key: 'rev', label: '本月营收', value: data.value?.month_revenue ?? 0, display: formatYuan(data.value?.month_revenue ?? 0), unit: '元' },
    { key: 'alert', label: '待处理告警', value: data.value?.pending_alerts ?? 0, display: String(data.value?.pending_alerts ?? 0), unit: '' },
    { key: 'low', label: '低库存 SKU', value: data.value?.low_stock_skus ?? 0, display: String(data.value?.low_stock_skus ?? 0), unit: '' }
]);
function formatYuan(v) {
    if (v >= 10000)
        return (v / 10000).toFixed(1) + 'w';
    if (v >= 1000)
        return (v / 1000).toFixed(1) + 'k';
    return v.toFixed(0);
}
async function fetchData() {
    try {
        const r = await http.get('/stats/bigscreen');
        data.value = r.data;
        renderServiceChart();
    }
    catch (e) { /* interceptor 已 toast */ }
}
function renderServiceChart() {
    if (!serviceChartEl.value || !data.value)
        return;
    const dist = data.value.service_distribution || {};
    const entries = Object.entries(dist).map(([name, value]) => ({ name, value }));
    if (!serviceChart) {
        serviceChart = echarts.init(serviceChartEl.value);
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
    });
}
function updateClock() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const weekDays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
    now.value = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${weekDays[d.getDay()]} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}
function startPolling() {
    updateClock();
    fetchData();
    clockTimer = window.setInterval(updateClock, 1000);
    pollTimer = window.setInterval(fetchData, 30000); // 30 秒
}
function stopPolling() {
    if (clockTimer) {
        window.clearInterval(clockTimer);
        clockTimer = null;
    }
    if (pollTimer) {
        window.clearInterval(pollTimer);
        pollTimer = null;
    }
    if (serviceChart) {
        serviceChart.dispose();
        serviceChart = null;
    }
}
onMounted(() => {
    startPolling();
    window.addEventListener('resize', onResize);
});
onBeforeUnmount(() => {
    stopPolling();
    window.removeEventListener('resize', onResize);
});
function onResize() {
    serviceChart?.resize();
}
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
const __VLS_ctx = {};
let __VLS_components;
let __VLS_directives;
/** @type {__VLS_StyleScopedClasses['top-pets']} */ ;
/** @type {__VLS_StyleScopedClasses['top-pets']} */ ;
/** @type {__VLS_StyleScopedClasses['top-pets__rank']} */ ;
/** @type {__VLS_StyleScopedClasses['top-pets__rank']} */ ;
/** @type {__VLS_StyleScopedClasses['top-pets__rank']} */ ;
// CSS variable injection 
// CSS variable injection end 
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "bigscreen" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.header, __VLS_intrinsicElements.header)({
    ...{ class: "bigscreen__header" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.h1, __VLS_intrinsicElements.h1)({
    ...{ class: "bigscreen__title" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "bigscreen__clock" },
});
(__VLS_ctx.now);
__VLS_asFunctionalElement(__VLS_intrinsicElements.section, __VLS_intrinsicElements.section)({
    ...{ class: "bigscreen__stats" },
});
for (const [s] of __VLS_getVForSourceType((__VLS_ctx.stats))) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "stat" },
        key: (s.key),
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "stat__label" },
    });
    (s.label);
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "stat__value" },
        'data-value': (s.value),
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: "stat__num" },
    });
    (s.display);
    if (s.unit) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
            ...{ class: "stat__unit" },
        });
        (s.unit);
    }
}
__VLS_asFunctionalElement(__VLS_intrinsicElements.section, __VLS_intrinsicElements.section)({
    ...{ class: "bigscreen__charts" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "chart-card" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.h3, __VLS_intrinsicElements.h3)({
    ...{ class: "chart-card__title" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ref: "serviceChartEl",
    ...{ class: "chart-card__chart" },
});
/** @type {typeof __VLS_ctx.serviceChartEl} */ ;
if (!__VLS_ctx.data) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "chart-card__empty" },
    });
}
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "chart-card" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.h3, __VLS_intrinsicElements.h3)({
    ...{ class: "chart-card__title" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.ul, __VLS_intrinsicElements.ul)({
    ...{ class: "top-pets" },
});
for (const [p, i] of __VLS_getVForSourceType((__VLS_ctx.data?.top_pets || []))) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.li, __VLS_intrinsicElements.li)({
        key: (p.name),
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: "top-pets__rank" },
        'data-rank': (i + 1),
    });
    (i + 1);
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: "top-pets__name" },
    });
    (p.name);
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: "top-pets__visits" },
    });
    (p.visits);
}
if (!__VLS_ctx.data?.top_pets?.length) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.li, __VLS_intrinsicElements.li)({
        ...{ class: "top-pets__empty" },
    });
}
/** @type {__VLS_StyleScopedClasses['bigscreen']} */ ;
/** @type {__VLS_StyleScopedClasses['bigscreen__header']} */ ;
/** @type {__VLS_StyleScopedClasses['bigscreen__title']} */ ;
/** @type {__VLS_StyleScopedClasses['bigscreen__clock']} */ ;
/** @type {__VLS_StyleScopedClasses['bigscreen__stats']} */ ;
/** @type {__VLS_StyleScopedClasses['stat']} */ ;
/** @type {__VLS_StyleScopedClasses['stat__label']} */ ;
/** @type {__VLS_StyleScopedClasses['stat__value']} */ ;
/** @type {__VLS_StyleScopedClasses['stat__num']} */ ;
/** @type {__VLS_StyleScopedClasses['stat__unit']} */ ;
/** @type {__VLS_StyleScopedClasses['bigscreen__charts']} */ ;
/** @type {__VLS_StyleScopedClasses['chart-card']} */ ;
/** @type {__VLS_StyleScopedClasses['chart-card__title']} */ ;
/** @type {__VLS_StyleScopedClasses['chart-card__chart']} */ ;
/** @type {__VLS_StyleScopedClasses['chart-card__empty']} */ ;
/** @type {__VLS_StyleScopedClasses['chart-card']} */ ;
/** @type {__VLS_StyleScopedClasses['chart-card__title']} */ ;
/** @type {__VLS_StyleScopedClasses['top-pets']} */ ;
/** @type {__VLS_StyleScopedClasses['top-pets__rank']} */ ;
/** @type {__VLS_StyleScopedClasses['top-pets__name']} */ ;
/** @type {__VLS_StyleScopedClasses['top-pets__visits']} */ ;
/** @type {__VLS_StyleScopedClasses['top-pets__empty']} */ ;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            data: data,
            now: now,
            serviceChartEl: serviceChartEl,
            stats: stats,
        };
    },
});
export default (await import('vue')).defineComponent({
    setup() {
        return {};
    },
});
; /* PartiallyEnd: #4569/main.vue */
//# sourceMappingURL=BigscreenView.vue.js.map