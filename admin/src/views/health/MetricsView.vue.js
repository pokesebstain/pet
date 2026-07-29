import { onMounted, ref } from 'vue';
import DataTable from '@/components/common/DataTable.vue';
import { formatDateTime } from '@/utils/format';
import { listPage } from '@/utils/http';
const items = ref([]);
const total = ref(0);
const loading = ref(false);
const page = ref(1);
const pageSize = ref(20);
const petId = ref('');
async function reload() {
    loading.value = true;
    try {
        const r = await listPage('/health/metrics', {
            page: page.value, page_size: pageSize.value, pet_id: petId.value || undefined
        });
        items.value = r.items;
        total.value = r.total;
    }
    finally {
        loading.value = false;
    }
}
onMounted(reload);
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
const __VLS_ctx = {};
let __VLS_components;
let __VLS_directives;
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({});
__VLS_asFunctionalElement(__VLS_intrinsicElements.h2, __VLS_intrinsicElements.h2)({});
/** @type {[typeof DataTable, typeof DataTable, ]} */ ;
// @ts-ignore
const __VLS_0 = __VLS_asFunctionalComponent(DataTable, new DataTable({
    ...{ 'onPageChange': {} },
    ...{ 'onSizeChange': {} },
    items: (__VLS_ctx.items),
    total: (__VLS_ctx.total),
    loading: (__VLS_ctx.loading),
}));
const __VLS_1 = __VLS_0({
    ...{ 'onPageChange': {} },
    ...{ 'onSizeChange': {} },
    items: (__VLS_ctx.items),
    total: (__VLS_ctx.total),
    loading: (__VLS_ctx.loading),
}, ...__VLS_functionalComponentArgsRest(__VLS_0));
let __VLS_3;
let __VLS_4;
let __VLS_5;
const __VLS_6 = {
    onPageChange: ((p) => { __VLS_ctx.page = p; __VLS_ctx.reload(); })
};
const __VLS_7 = {
    onSizeChange: ((s) => { __VLS_ctx.pageSize = s; __VLS_ctx.reload(); })
};
__VLS_2.slots.default;
{
    const { toolbar: __VLS_thisSlot } = __VLS_2.slots;
    const __VLS_8 = {}.ElInput;
    /** @type {[typeof __VLS_components.ElInput, typeof __VLS_components.elInput, ]} */ ;
    // @ts-ignore
    const __VLS_9 = __VLS_asFunctionalComponent(__VLS_8, new __VLS_8({
        ...{ 'onKeyup': {} },
        modelValue: (__VLS_ctx.petId),
        placeholder: "按宠物 ID 过滤",
        clearable: true,
        ...{ style: {} },
    }));
    const __VLS_10 = __VLS_9({
        ...{ 'onKeyup': {} },
        modelValue: (__VLS_ctx.petId),
        placeholder: "按宠物 ID 过滤",
        clearable: true,
        ...{ style: {} },
    }, ...__VLS_functionalComponentArgsRest(__VLS_9));
    let __VLS_12;
    let __VLS_13;
    let __VLS_14;
    const __VLS_15 = {
        onKeyup: (__VLS_ctx.reload)
    };
    var __VLS_11;
    const __VLS_16 = {}.ElButton;
    /** @type {[typeof __VLS_components.ElButton, typeof __VLS_components.elButton, typeof __VLS_components.ElButton, typeof __VLS_components.elButton, ]} */ ;
    // @ts-ignore
    const __VLS_17 = __VLS_asFunctionalComponent(__VLS_16, new __VLS_16({
        ...{ 'onClick': {} },
    }));
    const __VLS_18 = __VLS_17({
        ...{ 'onClick': {} },
    }, ...__VLS_functionalComponentArgsRest(__VLS_17));
    let __VLS_20;
    let __VLS_21;
    let __VLS_22;
    const __VLS_23 = {
        onClick: (__VLS_ctx.reload)
    };
    __VLS_19.slots.default;
    var __VLS_19;
}
const __VLS_24 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_25 = __VLS_asFunctionalComponent(__VLS_24, new __VLS_24({
    prop: "metric_id",
    label: "ID",
}));
const __VLS_26 = __VLS_25({
    prop: "metric_id",
    label: "ID",
}, ...__VLS_functionalComponentArgsRest(__VLS_25));
const __VLS_28 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_29 = __VLS_asFunctionalComponent(__VLS_28, new __VLS_28({
    prop: "pet_id",
    label: "宠物",
}));
const __VLS_30 = __VLS_29({
    prop: "pet_id",
    label: "宠物",
}, ...__VLS_functionalComponentArgsRest(__VLS_29));
const __VLS_32 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_33 = __VLS_asFunctionalComponent(__VLS_32, new __VLS_32({
    prop: "metric_type",
    label: "指标",
}));
const __VLS_34 = __VLS_33({
    prop: "metric_type",
    label: "指标",
}, ...__VLS_functionalComponentArgsRest(__VLS_33));
const __VLS_36 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_37 = __VLS_asFunctionalComponent(__VLS_36, new __VLS_36({
    prop: "value",
    label: "值",
}));
const __VLS_38 = __VLS_37({
    prop: "value",
    label: "值",
}, ...__VLS_functionalComponentArgsRest(__VLS_37));
const __VLS_40 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_41 = __VLS_asFunctionalComponent(__VLS_40, new __VLS_40({
    prop: "recorded_at",
    label: "时间",
}));
const __VLS_42 = __VLS_41({
    prop: "recorded_at",
    label: "时间",
}, ...__VLS_functionalComponentArgsRest(__VLS_41));
__VLS_43.slots.default;
{
    const { default: __VLS_thisSlot } = __VLS_43.slots;
    const [{ row }] = __VLS_getSlotParams(__VLS_thisSlot);
    (__VLS_ctx.formatDateTime(row.recorded_at));
}
var __VLS_43;
const __VLS_44 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_45 = __VLS_asFunctionalComponent(__VLS_44, new __VLS_44({
    prop: "source",
    label: "来源",
}));
const __VLS_46 = __VLS_45({
    prop: "source",
    label: "来源",
}, ...__VLS_functionalComponentArgsRest(__VLS_45));
var __VLS_2;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            DataTable: DataTable,
            formatDateTime: formatDateTime,
            items: items,
            total: total,
            loading: loading,
            page: page,
            pageSize: pageSize,
            petId: petId,
            reload: reload,
        };
    },
});
export default (await import('vue')).defineComponent({
    setup() {
        return {};
    },
});
; /* PartiallyEnd: #4569/main.vue */
//# sourceMappingURL=MetricsView.vue.js.map