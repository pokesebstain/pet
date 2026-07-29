import { onMounted, ref } from 'vue';
import { http } from '@/api/client';
import StatCard from '@/components/common/StatCard.vue';
const stats = ref({
    today_appointments: 0,
    today_new_customers: 0,
    pending_alerts: 0,
    low_stock_skus: 0,
    recent_revenue: 0
});
onMounted(async () => {
    try {
        const { data } = await http.get('/stats/overview');
        stats.value = data;
    }
    catch (e) { /* interceptor 已 toast */ }
});
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
const __VLS_ctx = {};
let __VLS_components;
let __VLS_directives;
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({});
__VLS_asFunctionalElement(__VLS_intrinsicElements.h2, __VLS_intrinsicElements.h2)({});
const __VLS_0 = {}.ElRow;
/** @type {[typeof __VLS_components.ElRow, typeof __VLS_components.elRow, typeof __VLS_components.ElRow, typeof __VLS_components.elRow, ]} */ ;
// @ts-ignore
const __VLS_1 = __VLS_asFunctionalComponent(__VLS_0, new __VLS_0({
    gutter: (12),
}));
const __VLS_2 = __VLS_1({
    gutter: (12),
}, ...__VLS_functionalComponentArgsRest(__VLS_1));
__VLS_3.slots.default;
const __VLS_4 = {}.ElCol;
/** @type {[typeof __VLS_components.ElCol, typeof __VLS_components.elCol, typeof __VLS_components.ElCol, typeof __VLS_components.elCol, ]} */ ;
// @ts-ignore
const __VLS_5 = __VLS_asFunctionalComponent(__VLS_4, new __VLS_4({
    span: (6),
}));
const __VLS_6 = __VLS_5({
    span: (6),
}, ...__VLS_functionalComponentArgsRest(__VLS_5));
__VLS_7.slots.default;
/** @type {[typeof StatCard, ]} */ ;
// @ts-ignore
const __VLS_8 = __VLS_asFunctionalComponent(StatCard, new StatCard({
    label: "今日预约",
    value: (__VLS_ctx.stats.today_appointments ?? 0),
}));
const __VLS_9 = __VLS_8({
    label: "今日预约",
    value: (__VLS_ctx.stats.today_appointments ?? 0),
}, ...__VLS_functionalComponentArgsRest(__VLS_8));
var __VLS_7;
const __VLS_11 = {}.ElCol;
/** @type {[typeof __VLS_components.ElCol, typeof __VLS_components.elCol, typeof __VLS_components.ElCol, typeof __VLS_components.elCol, ]} */ ;
// @ts-ignore
const __VLS_12 = __VLS_asFunctionalComponent(__VLS_11, new __VLS_11({
    span: (6),
}));
const __VLS_13 = __VLS_12({
    span: (6),
}, ...__VLS_functionalComponentArgsRest(__VLS_12));
__VLS_14.slots.default;
/** @type {[typeof StatCard, ]} */ ;
// @ts-ignore
const __VLS_15 = __VLS_asFunctionalComponent(StatCard, new StatCard({
    label: "今日新增客户",
    value: (__VLS_ctx.stats.today_new_customers ?? 0),
}));
const __VLS_16 = __VLS_15({
    label: "今日新增客户",
    value: (__VLS_ctx.stats.today_new_customers ?? 0),
}, ...__VLS_functionalComponentArgsRest(__VLS_15));
var __VLS_14;
const __VLS_18 = {}.ElCol;
/** @type {[typeof __VLS_components.ElCol, typeof __VLS_components.elCol, typeof __VLS_components.ElCol, typeof __VLS_components.elCol, ]} */ ;
// @ts-ignore
const __VLS_19 = __VLS_asFunctionalComponent(__VLS_18, new __VLS_18({
    span: (6),
}));
const __VLS_20 = __VLS_19({
    span: (6),
}, ...__VLS_functionalComponentArgsRest(__VLS_19));
__VLS_21.slots.default;
/** @type {[typeof StatCard, ]} */ ;
// @ts-ignore
const __VLS_22 = __VLS_asFunctionalComponent(StatCard, new StatCard({
    label: "待处理告警",
    value: (__VLS_ctx.stats.pending_alerts ?? 0),
}));
const __VLS_23 = __VLS_22({
    label: "待处理告警",
    value: (__VLS_ctx.stats.pending_alerts ?? 0),
}, ...__VLS_functionalComponentArgsRest(__VLS_22));
var __VLS_21;
const __VLS_25 = {}.ElCol;
/** @type {[typeof __VLS_components.ElCol, typeof __VLS_components.elCol, typeof __VLS_components.ElCol, typeof __VLS_components.elCol, ]} */ ;
// @ts-ignore
const __VLS_26 = __VLS_asFunctionalComponent(__VLS_25, new __VLS_25({
    span: (6),
}));
const __VLS_27 = __VLS_26({
    span: (6),
}, ...__VLS_functionalComponentArgsRest(__VLS_26));
__VLS_28.slots.default;
/** @type {[typeof StatCard, ]} */ ;
// @ts-ignore
const __VLS_29 = __VLS_asFunctionalComponent(StatCard, new StatCard({
    label: "低库存 SKU",
    value: (__VLS_ctx.stats.low_stock_skus ?? 0),
}));
const __VLS_30 = __VLS_29({
    label: "低库存 SKU",
    value: (__VLS_ctx.stats.low_stock_skus ?? 0),
}, ...__VLS_functionalComponentArgsRest(__VLS_29));
var __VLS_28;
var __VLS_3;
const __VLS_32 = {}.ElRow;
/** @type {[typeof __VLS_components.ElRow, typeof __VLS_components.elRow, typeof __VLS_components.ElRow, typeof __VLS_components.elRow, ]} */ ;
// @ts-ignore
const __VLS_33 = __VLS_asFunctionalComponent(__VLS_32, new __VLS_32({
    gutter: (12),
}));
const __VLS_34 = __VLS_33({
    gutter: (12),
}, ...__VLS_functionalComponentArgsRest(__VLS_33));
__VLS_35.slots.default;
const __VLS_36 = {}.ElCol;
/** @type {[typeof __VLS_components.ElCol, typeof __VLS_components.elCol, typeof __VLS_components.ElCol, typeof __VLS_components.elCol, ]} */ ;
// @ts-ignore
const __VLS_37 = __VLS_asFunctionalComponent(__VLS_36, new __VLS_36({
    span: (12),
}));
const __VLS_38 = __VLS_37({
    span: (12),
}, ...__VLS_functionalComponentArgsRest(__VLS_37));
__VLS_39.slots.default;
/** @type {[typeof StatCard, ]} */ ;
// @ts-ignore
const __VLS_40 = __VLS_asFunctionalComponent(StatCard, new StatCard({
    label: "本月营收 (元)",
    value: (__VLS_ctx.stats.recent_revenue ?? 0),
}));
const __VLS_41 = __VLS_40({
    label: "本月营收 (元)",
    value: (__VLS_ctx.stats.recent_revenue ?? 0),
}, ...__VLS_functionalComponentArgsRest(__VLS_40));
var __VLS_39;
var __VLS_35;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            StatCard: StatCard,
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
//# sourceMappingURL=DashboardView.vue.js.map