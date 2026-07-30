import { onMounted, ref } from 'vue';
import StatCard from '@/components/common/StatCard.vue';
import TodoPanel from '@/components/common/TodoPanel.vue';
import { dashboardApi } from '@/api/dashboard';
const stats = ref({
    today_appointments: 0,
    today_new_customers: 0,
    pending_alerts: 0,
    low_stock_skus: 0,
    recent_revenue: 0
});
const todos = ref([]);
const appointmentsSpark = ref([]);
const customersSpark = ref([]);
const alertsSpark = ref([]);
onMounted(async () => {
    try {
        stats.value = await dashboardApi.overview();
    }
    catch (e) { /* interceptor 已 toast */ }
    try {
        todos.value = await dashboardApi.todos();
    }
    catch (e) { /* interceptor 已 toast */ }
    try {
        const points = await dashboardApi.trends(7);
        appointmentsSpark.value = points.map((p) => p.appointments);
        customersSpark.value = points.map((p) => p.new_customers);
        alertsSpark.value = points.map((p) => p.health_alerts);
    }
    catch (e) { /* interceptor 已 toast */ }
});
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
const __VLS_ctx = {};
let __VLS_components;
let __VLS_directives;
// CSS variable injection 
// CSS variable injection end 
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "dashboard" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.h2, __VLS_intrinsicElements.h2)({});
/** @type {[typeof TodoPanel, ]} */ ;
// @ts-ignore
const __VLS_0 = __VLS_asFunctionalComponent(TodoPanel, new TodoPanel({
    todos: (__VLS_ctx.todos),
}));
const __VLS_1 = __VLS_0({
    todos: (__VLS_ctx.todos),
}, ...__VLS_functionalComponentArgsRest(__VLS_0));
const __VLS_3 = {}.ElRow;
/** @type {[typeof __VLS_components.ElRow, typeof __VLS_components.elRow, typeof __VLS_components.ElRow, typeof __VLS_components.elRow, ]} */ ;
// @ts-ignore
const __VLS_4 = __VLS_asFunctionalComponent(__VLS_3, new __VLS_3({
    gutter: (12),
}));
const __VLS_5 = __VLS_4({
    gutter: (12),
}, ...__VLS_functionalComponentArgsRest(__VLS_4));
__VLS_6.slots.default;
const __VLS_7 = {}.ElCol;
/** @type {[typeof __VLS_components.ElCol, typeof __VLS_components.elCol, typeof __VLS_components.ElCol, typeof __VLS_components.elCol, ]} */ ;
// @ts-ignore
const __VLS_8 = __VLS_asFunctionalComponent(__VLS_7, new __VLS_7({
    span: (6),
}));
const __VLS_9 = __VLS_8({
    span: (6),
}, ...__VLS_functionalComponentArgsRest(__VLS_8));
__VLS_10.slots.default;
/** @type {[typeof StatCard, ]} */ ;
// @ts-ignore
const __VLS_11 = __VLS_asFunctionalComponent(StatCard, new StatCard({
    ...{ 'onClick': {} },
    label: "今日预约",
    value: (__VLS_ctx.stats.today_appointments),
    sparkline: (__VLS_ctx.appointmentsSpark),
}));
const __VLS_12 = __VLS_11({
    ...{ 'onClick': {} },
    label: "今日预约",
    value: (__VLS_ctx.stats.today_appointments),
    sparkline: (__VLS_ctx.appointmentsSpark),
}, ...__VLS_functionalComponentArgsRest(__VLS_11));
let __VLS_14;
let __VLS_15;
let __VLS_16;
const __VLS_17 = {
    onClick: (...[$event]) => {
        __VLS_ctx.$router.push('/appointments');
    }
};
var __VLS_13;
var __VLS_10;
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
    ...{ 'onClick': {} },
    label: "今日新增客户",
    value: (__VLS_ctx.stats.today_new_customers),
    sparkline: (__VLS_ctx.customersSpark),
    color: "#409eff",
}));
const __VLS_23 = __VLS_22({
    ...{ 'onClick': {} },
    label: "今日新增客户",
    value: (__VLS_ctx.stats.today_new_customers),
    sparkline: (__VLS_ctx.customersSpark),
    color: "#409eff",
}, ...__VLS_functionalComponentArgsRest(__VLS_22));
let __VLS_25;
let __VLS_26;
let __VLS_27;
const __VLS_28 = {
    onClick: (...[$event]) => {
        __VLS_ctx.$router.push('/customers');
    }
};
var __VLS_24;
var __VLS_21;
const __VLS_29 = {}.ElCol;
/** @type {[typeof __VLS_components.ElCol, typeof __VLS_components.elCol, typeof __VLS_components.ElCol, typeof __VLS_components.elCol, ]} */ ;
// @ts-ignore
const __VLS_30 = __VLS_asFunctionalComponent(__VLS_29, new __VLS_29({
    span: (6),
}));
const __VLS_31 = __VLS_30({
    span: (6),
}, ...__VLS_functionalComponentArgsRest(__VLS_30));
__VLS_32.slots.default;
/** @type {[typeof StatCard, ]} */ ;
// @ts-ignore
const __VLS_33 = __VLS_asFunctionalComponent(StatCard, new StatCard({
    ...{ 'onClick': {} },
    label: "待处理告警",
    value: (__VLS_ctx.stats.pending_alerts),
    sparkline: (__VLS_ctx.alertsSpark),
    color: "#f56c6c",
}));
const __VLS_34 = __VLS_33({
    ...{ 'onClick': {} },
    label: "待处理告警",
    value: (__VLS_ctx.stats.pending_alerts),
    sparkline: (__VLS_ctx.alertsSpark),
    color: "#f56c6c",
}, ...__VLS_functionalComponentArgsRest(__VLS_33));
let __VLS_36;
let __VLS_37;
let __VLS_38;
const __VLS_39 = {
    onClick: (...[$event]) => {
        __VLS_ctx.$router.push('/health/alerts');
    }
};
var __VLS_35;
var __VLS_32;
const __VLS_40 = {}.ElCol;
/** @type {[typeof __VLS_components.ElCol, typeof __VLS_components.elCol, typeof __VLS_components.ElCol, typeof __VLS_components.elCol, ]} */ ;
// @ts-ignore
const __VLS_41 = __VLS_asFunctionalComponent(__VLS_40, new __VLS_40({
    span: (6),
}));
const __VLS_42 = __VLS_41({
    span: (6),
}, ...__VLS_functionalComponentArgsRest(__VLS_41));
__VLS_43.slots.default;
/** @type {[typeof StatCard, ]} */ ;
// @ts-ignore
const __VLS_44 = __VLS_asFunctionalComponent(StatCard, new StatCard({
    ...{ 'onClick': {} },
    label: "低库存 SKU",
    value: (__VLS_ctx.stats.low_stock_skus),
}));
const __VLS_45 = __VLS_44({
    ...{ 'onClick': {} },
    label: "低库存 SKU",
    value: (__VLS_ctx.stats.low_stock_skus),
}, ...__VLS_functionalComponentArgsRest(__VLS_44));
let __VLS_47;
let __VLS_48;
let __VLS_49;
const __VLS_50 = {
    onClick: (...[$event]) => {
        __VLS_ctx.$router.push('/supply/skus');
    }
};
var __VLS_46;
var __VLS_43;
var __VLS_6;
const __VLS_51 = {}.ElRow;
/** @type {[typeof __VLS_components.ElRow, typeof __VLS_components.elRow, typeof __VLS_components.ElRow, typeof __VLS_components.elRow, ]} */ ;
// @ts-ignore
const __VLS_52 = __VLS_asFunctionalComponent(__VLS_51, new __VLS_51({
    gutter: (12),
}));
const __VLS_53 = __VLS_52({
    gutter: (12),
}, ...__VLS_functionalComponentArgsRest(__VLS_52));
__VLS_54.slots.default;
const __VLS_55 = {}.ElCol;
/** @type {[typeof __VLS_components.ElCol, typeof __VLS_components.elCol, typeof __VLS_components.ElCol, typeof __VLS_components.elCol, ]} */ ;
// @ts-ignore
const __VLS_56 = __VLS_asFunctionalComponent(__VLS_55, new __VLS_55({
    span: (12),
}));
const __VLS_57 = __VLS_56({
    span: (12),
}, ...__VLS_functionalComponentArgsRest(__VLS_56));
__VLS_58.slots.default;
/** @type {[typeof StatCard, ]} */ ;
// @ts-ignore
const __VLS_59 = __VLS_asFunctionalComponent(StatCard, new StatCard({
    label: "本月营收 (元)",
    value: (__VLS_ctx.stats.recent_revenue),
}));
const __VLS_60 = __VLS_59({
    label: "本月营收 (元)",
    value: (__VLS_ctx.stats.recent_revenue),
}, ...__VLS_functionalComponentArgsRest(__VLS_59));
var __VLS_58;
var __VLS_54;
/** @type {__VLS_StyleScopedClasses['dashboard']} */ ;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            StatCard: StatCard,
            TodoPanel: TodoPanel,
            stats: stats,
            todos: todos,
            appointmentsSpark: appointmentsSpark,
            customersSpark: customersSpark,
            alertsSpark: alertsSpark,
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