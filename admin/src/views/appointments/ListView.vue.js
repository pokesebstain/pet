import { onMounted, ref } from 'vue';
import { ElMessage } from 'element-plus';
import DataTable from '@/components/common/DataTable.vue';
import { appointmentsApi } from '@/api/appointments';
import { formatDateTime } from '@/utils/format';
const items = ref([]);
const total = ref(0);
const loading = ref(false);
const page = ref(1);
const pageSize = ref(20);
const statusFilter = ref(null);
const statuses = ['pending', 'confirmed', 'completed', 'cancelled'];
async function reload() {
    loading.value = true;
    try {
        const r = await appointmentsApi.list(page.value, pageSize.value, {
            status: statusFilter.value || undefined
        });
        items.value = r.items;
        total.value = r.total;
    }
    finally {
        loading.value = false;
    }
}
function statusTagType(s) {
    if (s === 'confirmed')
        return 'success';
    if (s === 'cancelled')
        return 'danger';
    if (s === 'completed')
        return 'info';
    return 'warning';
}
async function onCancel(id) {
    await appointmentsApi.cancel(id);
    ElMessage.success('已取消');
    await reload();
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
    const __VLS_8 = {}.ElSelect;
    /** @type {[typeof __VLS_components.ElSelect, typeof __VLS_components.elSelect, typeof __VLS_components.ElSelect, typeof __VLS_components.elSelect, ]} */ ;
    // @ts-ignore
    const __VLS_9 = __VLS_asFunctionalComponent(__VLS_8, new __VLS_8({
        ...{ 'onChange': {} },
        modelValue: (__VLS_ctx.statusFilter),
        placeholder: "状态",
        clearable: true,
        ...{ style: {} },
    }));
    const __VLS_10 = __VLS_9({
        ...{ 'onChange': {} },
        modelValue: (__VLS_ctx.statusFilter),
        placeholder: "状态",
        clearable: true,
        ...{ style: {} },
    }, ...__VLS_functionalComponentArgsRest(__VLS_9));
    let __VLS_12;
    let __VLS_13;
    let __VLS_14;
    const __VLS_15 = {
        onChange: (__VLS_ctx.reload)
    };
    __VLS_11.slots.default;
    for (const [s] of __VLS_getVForSourceType((__VLS_ctx.statuses))) {
        const __VLS_16 = {}.ElOption;
        /** @type {[typeof __VLS_components.ElOption, typeof __VLS_components.elOption, ]} */ ;
        // @ts-ignore
        const __VLS_17 = __VLS_asFunctionalComponent(__VLS_16, new __VLS_16({
            key: (s),
            label: (s),
            value: (s),
        }));
        const __VLS_18 = __VLS_17({
            key: (s),
            label: (s),
            value: (s),
        }, ...__VLS_functionalComponentArgsRest(__VLS_17));
    }
    var __VLS_11;
    const __VLS_20 = {}.ElButton;
    /** @type {[typeof __VLS_components.ElButton, typeof __VLS_components.elButton, typeof __VLS_components.ElButton, typeof __VLS_components.elButton, ]} */ ;
    // @ts-ignore
    const __VLS_21 = __VLS_asFunctionalComponent(__VLS_20, new __VLS_20({
        ...{ 'onClick': {} },
    }));
    const __VLS_22 = __VLS_21({
        ...{ 'onClick': {} },
    }, ...__VLS_functionalComponentArgsRest(__VLS_21));
    let __VLS_24;
    let __VLS_25;
    let __VLS_26;
    const __VLS_27 = {
        onClick: (__VLS_ctx.reload)
    };
    __VLS_23.slots.default;
    var __VLS_23;
}
const __VLS_28 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_29 = __VLS_asFunctionalComponent(__VLS_28, new __VLS_28({
    prop: "appointment_id",
    label: "ID",
}));
const __VLS_30 = __VLS_29({
    prop: "appointment_id",
    label: "ID",
}, ...__VLS_functionalComponentArgsRest(__VLS_29));
const __VLS_32 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_33 = __VLS_asFunctionalComponent(__VLS_32, new __VLS_32({
    prop: "customer_id",
    label: "客户",
}));
const __VLS_34 = __VLS_33({
    prop: "customer_id",
    label: "客户",
}, ...__VLS_functionalComponentArgsRest(__VLS_33));
const __VLS_36 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_37 = __VLS_asFunctionalComponent(__VLS_36, new __VLS_36({
    prop: "pet_id",
    label: "宠物",
}));
const __VLS_38 = __VLS_37({
    prop: "pet_id",
    label: "宠物",
}, ...__VLS_functionalComponentArgsRest(__VLS_37));
const __VLS_40 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_41 = __VLS_asFunctionalComponent(__VLS_40, new __VLS_40({
    prop: "service_type",
    label: "服务",
}));
const __VLS_42 = __VLS_41({
    prop: "service_type",
    label: "服务",
}, ...__VLS_functionalComponentArgsRest(__VLS_41));
const __VLS_44 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_45 = __VLS_asFunctionalComponent(__VLS_44, new __VLS_44({
    prop: "start_at",
    label: "开始时间",
}));
const __VLS_46 = __VLS_45({
    prop: "start_at",
    label: "开始时间",
}, ...__VLS_functionalComponentArgsRest(__VLS_45));
__VLS_47.slots.default;
{
    const { default: __VLS_thisSlot } = __VLS_47.slots;
    const [{ row }] = __VLS_getSlotParams(__VLS_thisSlot);
    (__VLS_ctx.formatDateTime(row.start_at));
}
var __VLS_47;
const __VLS_48 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_49 = __VLS_asFunctionalComponent(__VLS_48, new __VLS_48({
    prop: "status",
    label: "状态",
}));
const __VLS_50 = __VLS_49({
    prop: "status",
    label: "状态",
}, ...__VLS_functionalComponentArgsRest(__VLS_49));
__VLS_51.slots.default;
{
    const { default: __VLS_thisSlot } = __VLS_51.slots;
    const [{ row }] = __VLS_getSlotParams(__VLS_thisSlot);
    const __VLS_52 = {}.ElTag;
    /** @type {[typeof __VLS_components.ElTag, typeof __VLS_components.elTag, typeof __VLS_components.ElTag, typeof __VLS_components.elTag, ]} */ ;
    // @ts-ignore
    const __VLS_53 = __VLS_asFunctionalComponent(__VLS_52, new __VLS_52({
        type: (__VLS_ctx.statusTagType(row.status)),
    }));
    const __VLS_54 = __VLS_53({
        type: (__VLS_ctx.statusTagType(row.status)),
    }, ...__VLS_functionalComponentArgsRest(__VLS_53));
    __VLS_55.slots.default;
    (row.status);
    var __VLS_55;
}
var __VLS_51;
const __VLS_56 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_57 = __VLS_asFunctionalComponent(__VLS_56, new __VLS_56({
    label: "操作",
    width: "120",
}));
const __VLS_58 = __VLS_57({
    label: "操作",
    width: "120",
}, ...__VLS_functionalComponentArgsRest(__VLS_57));
__VLS_59.slots.default;
{
    const { default: __VLS_thisSlot } = __VLS_59.slots;
    const [{ row }] = __VLS_getSlotParams(__VLS_thisSlot);
    if (['pending', 'confirmed'].includes(row.status)) {
        const __VLS_60 = {}.ElPopconfirm;
        /** @type {[typeof __VLS_components.ElPopconfirm, typeof __VLS_components.elPopconfirm, typeof __VLS_components.ElPopconfirm, typeof __VLS_components.elPopconfirm, ]} */ ;
        // @ts-ignore
        const __VLS_61 = __VLS_asFunctionalComponent(__VLS_60, new __VLS_60({
            ...{ 'onConfirm': {} },
            title: "确认取消预约?",
        }));
        const __VLS_62 = __VLS_61({
            ...{ 'onConfirm': {} },
            title: "确认取消预约?",
        }, ...__VLS_functionalComponentArgsRest(__VLS_61));
        let __VLS_64;
        let __VLS_65;
        let __VLS_66;
        const __VLS_67 = {
            onConfirm: (...[$event]) => {
                if (!(['pending', 'confirmed'].includes(row.status)))
                    return;
                __VLS_ctx.onCancel(row.appointment_id);
            }
        };
        __VLS_63.slots.default;
        {
            const { reference: __VLS_thisSlot } = __VLS_63.slots;
            const __VLS_68 = {}.ElButton;
            /** @type {[typeof __VLS_components.ElButton, typeof __VLS_components.elButton, typeof __VLS_components.ElButton, typeof __VLS_components.elButton, ]} */ ;
            // @ts-ignore
            const __VLS_69 = __VLS_asFunctionalComponent(__VLS_68, new __VLS_68({
                text: true,
                type: "danger",
            }));
            const __VLS_70 = __VLS_69({
                text: true,
                type: "danger",
            }, ...__VLS_functionalComponentArgsRest(__VLS_69));
            __VLS_71.slots.default;
            var __VLS_71;
        }
        var __VLS_63;
    }
}
var __VLS_59;
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
            statusFilter: statusFilter,
            statuses: statuses,
            reload: reload,
            statusTagType: statusTagType,
            onCancel: onCancel,
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