import { onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import DataTable from '@/components/common/DataTable.vue';
import FormDrawer from '@/components/common/FormDrawer.vue';
import { listPage, createOne } from '@/utils/http';
import { formatDateTime } from '@/utils/format';
const items = ref([]);
const total = ref(0);
const loading = ref(false);
const page = ref(1);
const pageSize = ref(20);
const drawerOpen = ref(false);
const form = reactive({ topic: '', channel: 'wechat' });
const channels = ['wechat', 'sms', 'email'];
function statusTagType(s) {
    if (s === 'approved' || s === 'sent')
        return 'success';
    if (s === 'draft')
        return 'info';
    return 'warning';
}
async function reload() {
    loading.value = true;
    try {
        const r = await listPage('/marketing/contents', {
            page: page.value, page_size: pageSize.value
        });
        items.value = r.items;
        total.value = r.total;
    }
    finally {
        loading.value = false;
    }
}
async function onSubmit() {
    await createOne('/marketing/contents/generate', { ...form });
    ElMessage.success('已生成（draft）');
    drawerOpen.value = false;
    form.topic = '';
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
    const __VLS_8 = {}.ElButton;
    /** @type {[typeof __VLS_components.ElButton, typeof __VLS_components.elButton, typeof __VLS_components.ElButton, typeof __VLS_components.elButton, ]} */ ;
    // @ts-ignore
    const __VLS_9 = __VLS_asFunctionalComponent(__VLS_8, new __VLS_8({
        ...{ 'onClick': {} },
        type: "primary",
    }));
    const __VLS_10 = __VLS_9({
        ...{ 'onClick': {} },
        type: "primary",
    }, ...__VLS_functionalComponentArgsRest(__VLS_9));
    let __VLS_12;
    let __VLS_13;
    let __VLS_14;
    const __VLS_15 = {
        onClick: (...[$event]) => {
            __VLS_ctx.drawerOpen = true;
        }
    };
    __VLS_11.slots.default;
    var __VLS_11;
}
const __VLS_16 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_17 = __VLS_asFunctionalComponent(__VLS_16, new __VLS_16({
    prop: "content_id",
    label: "ID",
}));
const __VLS_18 = __VLS_17({
    prop: "content_id",
    label: "ID",
}, ...__VLS_functionalComponentArgsRest(__VLS_17));
const __VLS_20 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_21 = __VLS_asFunctionalComponent(__VLS_20, new __VLS_20({
    prop: "topic",
    label: "主题",
}));
const __VLS_22 = __VLS_21({
    prop: "topic",
    label: "主题",
}, ...__VLS_functionalComponentArgsRest(__VLS_21));
const __VLS_24 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_25 = __VLS_asFunctionalComponent(__VLS_24, new __VLS_24({
    prop: "channel",
    label: "渠道",
}));
const __VLS_26 = __VLS_25({
    prop: "channel",
    label: "渠道",
}, ...__VLS_functionalComponentArgsRest(__VLS_25));
const __VLS_28 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_29 = __VLS_asFunctionalComponent(__VLS_28, new __VLS_28({
    prop: "status",
    label: "状态",
}));
const __VLS_30 = __VLS_29({
    prop: "status",
    label: "状态",
}, ...__VLS_functionalComponentArgsRest(__VLS_29));
__VLS_31.slots.default;
{
    const { default: __VLS_thisSlot } = __VLS_31.slots;
    const [{ row }] = __VLS_getSlotParams(__VLS_thisSlot);
    const __VLS_32 = {}.ElTag;
    /** @type {[typeof __VLS_components.ElTag, typeof __VLS_components.elTag, typeof __VLS_components.ElTag, typeof __VLS_components.elTag, ]} */ ;
    // @ts-ignore
    const __VLS_33 = __VLS_asFunctionalComponent(__VLS_32, new __VLS_32({
        type: (__VLS_ctx.statusTagType(row.status)),
    }));
    const __VLS_34 = __VLS_33({
        type: (__VLS_ctx.statusTagType(row.status)),
    }, ...__VLS_functionalComponentArgsRest(__VLS_33));
    __VLS_35.slots.default;
    (row.status);
    var __VLS_35;
}
var __VLS_31;
const __VLS_36 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_37 = __VLS_asFunctionalComponent(__VLS_36, new __VLS_36({
    prop: "generated_at",
    label: "生成时间",
}));
const __VLS_38 = __VLS_37({
    prop: "generated_at",
    label: "生成时间",
}, ...__VLS_functionalComponentArgsRest(__VLS_37));
__VLS_39.slots.default;
{
    const { default: __VLS_thisSlot } = __VLS_39.slots;
    const [{ row }] = __VLS_getSlotParams(__VLS_thisSlot);
    (__VLS_ctx.formatDateTime(row.generated_at));
}
var __VLS_39;
var __VLS_2;
/** @type {[typeof FormDrawer, typeof FormDrawer, ]} */ ;
// @ts-ignore
const __VLS_40 = __VLS_asFunctionalComponent(FormDrawer, new FormDrawer({
    ...{ 'onSubmit': {} },
    modelValue: (__VLS_ctx.drawerOpen),
    title: "生成营销内容",
    form: (__VLS_ctx.form),
}));
const __VLS_41 = __VLS_40({
    ...{ 'onSubmit': {} },
    modelValue: (__VLS_ctx.drawerOpen),
    title: "生成营销内容",
    form: (__VLS_ctx.form),
}, ...__VLS_functionalComponentArgsRest(__VLS_40));
let __VLS_43;
let __VLS_44;
let __VLS_45;
const __VLS_46 = {
    onSubmit: (__VLS_ctx.onSubmit)
};
__VLS_42.slots.default;
{
    const { default: __VLS_thisSlot } = __VLS_42.slots;
    const [{ form }] = __VLS_getSlotParams(__VLS_thisSlot);
    const __VLS_47 = {}.ElFormItem;
    /** @type {[typeof __VLS_components.ElFormItem, typeof __VLS_components.elFormItem, typeof __VLS_components.ElFormItem, typeof __VLS_components.elFormItem, ]} */ ;
    // @ts-ignore
    const __VLS_48 = __VLS_asFunctionalComponent(__VLS_47, new __VLS_47({
        label: "主题",
    }));
    const __VLS_49 = __VLS_48({
        label: "主题",
    }, ...__VLS_functionalComponentArgsRest(__VLS_48));
    __VLS_50.slots.default;
    const __VLS_51 = {}.ElInput;
    /** @type {[typeof __VLS_components.ElInput, typeof __VLS_components.elInput, ]} */ ;
    // @ts-ignore
    const __VLS_52 = __VLS_asFunctionalComponent(__VLS_51, new __VLS_51({
        modelValue: (form.topic),
    }));
    const __VLS_53 = __VLS_52({
        modelValue: (form.topic),
    }, ...__VLS_functionalComponentArgsRest(__VLS_52));
    var __VLS_50;
    const __VLS_55 = {}.ElFormItem;
    /** @type {[typeof __VLS_components.ElFormItem, typeof __VLS_components.elFormItem, typeof __VLS_components.ElFormItem, typeof __VLS_components.elFormItem, ]} */ ;
    // @ts-ignore
    const __VLS_56 = __VLS_asFunctionalComponent(__VLS_55, new __VLS_55({
        label: "渠道",
    }));
    const __VLS_57 = __VLS_56({
        label: "渠道",
    }, ...__VLS_functionalComponentArgsRest(__VLS_56));
    __VLS_58.slots.default;
    const __VLS_59 = {}.ElSelect;
    /** @type {[typeof __VLS_components.ElSelect, typeof __VLS_components.elSelect, typeof __VLS_components.ElSelect, typeof __VLS_components.elSelect, ]} */ ;
    // @ts-ignore
    const __VLS_60 = __VLS_asFunctionalComponent(__VLS_59, new __VLS_59({
        modelValue: (form.channel),
    }));
    const __VLS_61 = __VLS_60({
        modelValue: (form.channel),
    }, ...__VLS_functionalComponentArgsRest(__VLS_60));
    __VLS_62.slots.default;
    for (const [c] of __VLS_getVForSourceType((__VLS_ctx.channels))) {
        const __VLS_63 = {}.ElOption;
        /** @type {[typeof __VLS_components.ElOption, typeof __VLS_components.elOption, ]} */ ;
        // @ts-ignore
        const __VLS_64 = __VLS_asFunctionalComponent(__VLS_63, new __VLS_63({
            key: (c),
            label: (c),
            value: (c),
        }));
        const __VLS_65 = __VLS_64({
            key: (c),
            label: (c),
            value: (c),
        }, ...__VLS_functionalComponentArgsRest(__VLS_64));
    }
    var __VLS_62;
    var __VLS_58;
}
var __VLS_42;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            DataTable: DataTable,
            FormDrawer: FormDrawer,
            formatDateTime: formatDateTime,
            items: items,
            total: total,
            loading: loading,
            page: page,
            pageSize: pageSize,
            drawerOpen: drawerOpen,
            form: form,
            channels: channels,
            statusTagType: statusTagType,
            reload: reload,
            onSubmit: onSubmit,
        };
    },
});
export default (await import('vue')).defineComponent({
    setup() {
        return {};
    },
});
; /* PartiallyEnd: #4569/main.vue */
//# sourceMappingURL=ContentsView.vue.js.map