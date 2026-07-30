import { onMounted, ref, watch, nextTick } from 'vue';
import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { CanvasRenderer } from 'echarts/renderers';
echarts.use([LineChart, CanvasRenderer]);
const props = defineProps();
const __VLS_emit = defineEmits();
const chartEl = ref();
let chart;
function render() {
    if (!chartEl.value || !props.sparkline || !props.sparkline.length)
        return;
    if (!chart)
        chart = echarts.init(chartEl.value);
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
    });
    chart.resize();
}
onMounted(() => nextTick(render));
watch(() => props.sparkline, () => nextTick(render));
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
const __VLS_ctx = {};
let __VLS_components;
let __VLS_directives;
/** @type {__VLS_StyleScopedClasses['stat-card__trend']} */ ;
// CSS variable injection 
// CSS variable injection end 
const __VLS_0 = {}.ElCard;
/** @type {[typeof __VLS_components.ElCard, typeof __VLS_components.elCard, typeof __VLS_components.ElCard, typeof __VLS_components.elCard, ]} */ ;
// @ts-ignore
const __VLS_1 = __VLS_asFunctionalComponent(__VLS_0, new __VLS_0({
    ...{ 'onClick': {} },
    shadow: "hover",
    ...{ class: "stat-card" },
}));
const __VLS_2 = __VLS_1({
    ...{ 'onClick': {} },
    shadow: "hover",
    ...{ class: "stat-card" },
}, ...__VLS_functionalComponentArgsRest(__VLS_1));
let __VLS_4;
let __VLS_5;
let __VLS_6;
const __VLS_7 = {
    onClick: (...[$event]) => {
        __VLS_ctx.$emit('click');
    }
};
var __VLS_8 = {};
__VLS_3.slots.default;
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "stat-card__top" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "stat-card__label" },
});
(__VLS_ctx.label);
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "stat-card__value" },
});
(__VLS_ctx.value);
if (__VLS_ctx.sparkline && __VLS_ctx.sparkline.length) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div)({
        ref: "chartEl",
        ...{ class: "stat-card__spark" },
    });
    /** @type {typeof __VLS_ctx.chartEl} */ ;
}
if (__VLS_ctx.trend !== undefined) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "stat-card__trend" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: (__VLS_ctx.trend >= 0 ? 'up' : 'down') },
    });
    (__VLS_ctx.trend >= 0 ? '↑' : '↓');
    (Math.abs(__VLS_ctx.trend));
}
var __VLS_3;
/** @type {__VLS_StyleScopedClasses['stat-card']} */ ;
/** @type {__VLS_StyleScopedClasses['stat-card__top']} */ ;
/** @type {__VLS_StyleScopedClasses['stat-card__label']} */ ;
/** @type {__VLS_StyleScopedClasses['stat-card__value']} */ ;
/** @type {__VLS_StyleScopedClasses['stat-card__spark']} */ ;
/** @type {__VLS_StyleScopedClasses['stat-card__trend']} */ ;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            chartEl: chartEl,
        };
    },
    __typeEmits: {},
    __typeProps: {},
});
export default (await import('vue')).defineComponent({
    setup() {
        return {};
    },
    __typeEmits: {},
    __typeProps: {},
});
; /* PartiallyEnd: #4569/main.vue */
//# sourceMappingURL=StatCard.vue.js.map