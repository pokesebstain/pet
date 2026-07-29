import { onMounted, ref } from 'vue';
import DataTable from '@/components/common/DataTable.vue';
import { petsApi } from '@/api/pets';
const items = ref([]);
const total = ref(0);
const loading = ref(false);
const page = ref(1);
const pageSize = ref(20);
const search = ref('');
async function reload() {
    loading.value = true;
    try {
        const r = await petsApi.list(page.value, pageSize.value, search.value || undefined);
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
        modelValue: (__VLS_ctx.search),
        placeholder: "搜索名字/品种",
        clearable: true,
        ...{ style: {} },
    }));
    const __VLS_10 = __VLS_9({
        ...{ 'onKeyup': {} },
        modelValue: (__VLS_ctx.search),
        placeholder: "搜索名字/品种",
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
    prop: "name",
    label: "名字",
}));
const __VLS_26 = __VLS_25({
    prop: "name",
    label: "名字",
}, ...__VLS_functionalComponentArgsRest(__VLS_25));
const __VLS_28 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_29 = __VLS_asFunctionalComponent(__VLS_28, new __VLS_28({
    prop: "species",
    label: "物种",
}));
const __VLS_30 = __VLS_29({
    prop: "species",
    label: "物种",
}, ...__VLS_functionalComponentArgsRest(__VLS_29));
const __VLS_32 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_33 = __VLS_asFunctionalComponent(__VLS_32, new __VLS_32({
    prop: "breed",
    label: "品种",
}));
const __VLS_34 = __VLS_33({
    prop: "breed",
    label: "品种",
}, ...__VLS_functionalComponentArgsRest(__VLS_33));
const __VLS_36 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_37 = __VLS_asFunctionalComponent(__VLS_36, new __VLS_36({
    prop: "weight_kg",
    label: "体重(kg)",
}));
const __VLS_38 = __VLS_37({
    prop: "weight_kg",
    label: "体重(kg)",
}, ...__VLS_functionalComponentArgsRest(__VLS_37));
const __VLS_40 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_41 = __VLS_asFunctionalComponent(__VLS_40, new __VLS_40({
    prop: "life_stage",
    label: "生命阶段",
}));
const __VLS_42 = __VLS_41({
    prop: "life_stage",
    label: "生命阶段",
}, ...__VLS_functionalComponentArgsRest(__VLS_41));
const __VLS_44 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_45 = __VLS_asFunctionalComponent(__VLS_44, new __VLS_44({
    prop: "onboarding_pending",
    label: "待完善",
}));
const __VLS_46 = __VLS_45({
    prop: "onboarding_pending",
    label: "待完善",
}, ...__VLS_functionalComponentArgsRest(__VLS_45));
__VLS_47.slots.default;
{
    const { default: __VLS_thisSlot } = __VLS_47.slots;
    const [{ row }] = __VLS_getSlotParams(__VLS_thisSlot);
    if (row.onboarding_pending) {
        const __VLS_48 = {}.ElTag;
        /** @type {[typeof __VLS_components.ElTag, typeof __VLS_components.elTag, typeof __VLS_components.ElTag, typeof __VLS_components.elTag, ]} */ ;
        // @ts-ignore
        const __VLS_49 = __VLS_asFunctionalComponent(__VLS_48, new __VLS_48({
            type: "warning",
            size: "small",
        }));
        const __VLS_50 = __VLS_49({
            type: "warning",
            size: "small",
        }, ...__VLS_functionalComponentArgsRest(__VLS_49));
        __VLS_51.slots.default;
        var __VLS_51;
    }
    else {
        const __VLS_52 = {}.ElTag;
        /** @type {[typeof __VLS_components.ElTag, typeof __VLS_components.elTag, typeof __VLS_components.ElTag, typeof __VLS_components.elTag, ]} */ ;
        // @ts-ignore
        const __VLS_53 = __VLS_asFunctionalComponent(__VLS_52, new __VLS_52({
            type: "success",
            size: "small",
        }));
        const __VLS_54 = __VLS_53({
            type: "success",
            size: "small",
        }, ...__VLS_functionalComponentArgsRest(__VLS_53));
        __VLS_55.slots.default;
        var __VLS_55;
    }
}
var __VLS_47;
var __VLS_2;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            DataTable: DataTable,
            items: items,
            total: total,
            loading: loading,
            page: page,
            pageSize: pageSize,
            search: search,
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
//# sourceMappingURL=ListView.vue.js.map