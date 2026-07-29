import { onMounted, ref } from 'vue';
import { http } from '@/api/client';
import StatCard from '@/components/common/StatCard.vue';
const items = ref([]);
onMounted(async () => {
    const { data } = await http.get('/operations/ltv');
    items.value = data;
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
for (const [seg] of __VLS_getVForSourceType((__VLS_ctx.items))) {
    const __VLS_4 = {}.ElCol;
    /** @type {[typeof __VLS_components.ElCol, typeof __VLS_components.elCol, typeof __VLS_components.ElCol, typeof __VLS_components.elCol, ]} */ ;
    // @ts-ignore
    const __VLS_5 = __VLS_asFunctionalComponent(__VLS_4, new __VLS_4({
        key: (seg.segment),
        span: (6),
    }));
    const __VLS_6 = __VLS_5({
        key: (seg.segment),
        span: (6),
    }, ...__VLS_functionalComponentArgsRest(__VLS_5));
    __VLS_7.slots.default;
    /** @type {[typeof StatCard, ]} */ ;
    // @ts-ignore
    const __VLS_8 = __VLS_asFunctionalComponent(StatCard, new StatCard({
        label: (seg.segment),
        value: (seg.customer_count),
        trend: (undefined),
    }));
    const __VLS_9 = __VLS_8({
        label: (seg.segment),
        value: (seg.customer_count),
        trend: (undefined),
    }, ...__VLS_functionalComponentArgsRest(__VLS_8));
    const __VLS_11 = {}.ElCard;
    /** @type {[typeof __VLS_components.ElCard, typeof __VLS_components.elCard, typeof __VLS_components.ElCard, typeof __VLS_components.elCard, ]} */ ;
    // @ts-ignore
    const __VLS_12 = __VLS_asFunctionalComponent(__VLS_11, new __VLS_11({
        shadow: "never",
        ...{ style: {} },
    }));
    const __VLS_13 = __VLS_12({
        shadow: "never",
        ...{ style: {} },
    }, ...__VLS_functionalComponentArgsRest(__VLS_12));
    __VLS_14.slots.default;
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({});
    (seg.avg_ltv.toFixed(2));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({});
    (seg.total_ltv.toFixed(2));
    var __VLS_14;
    var __VLS_7;
}
var __VLS_3;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            StatCard: StatCard,
            items: items,
        };
    },
});
export default (await import('vue')).defineComponent({
    setup() {
        return {};
    },
});
; /* PartiallyEnd: #4569/main.vue */
//# sourceMappingURL=LtvView.vue.js.map