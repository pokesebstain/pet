import { onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import DataTable from '@/components/common/DataTable.vue';
import FormDrawer from '@/components/common/FormDrawer.vue';
import { customersApi } from '@/api/customers';
const router = useRouter();
const items = ref([]);
const total = ref(0);
const loading = ref(false);
const page = ref(1);
const pageSize = ref(20);
const search = ref('');
const drawerOpen = ref(false);
const editing = ref(false);
const editingId = ref(null);
const form = reactive({ name: '', phone: '' });
async function reload() {
    loading.value = true;
    try {
        const r = await customersApi.list(page.value, pageSize.value, search.value || undefined);
        items.value = r.items;
        total.value = r.total;
    }
    finally {
        loading.value = false;
    }
}
function openCreate() {
    editing.value = false;
    editingId.value = null;
    form.name = '';
    form.phone = '';
    drawerOpen.value = true;
}
function openEdit(row) {
    editing.value = true;
    editingId.value = row.customer_id;
    form.name = row.name;
    form.phone = row.phone ?? '';
    drawerOpen.value = true;
}
async function onSubmit() {
    try {
        if (editing.value && editingId.value) {
            await customersApi.update(editingId.value, { name: form.name, phone: form.phone || undefined });
            ElMessage.success('已更新');
        }
        else {
            await customersApi.create({ name: form.name, phone: form.phone || undefined });
            ElMessage.success('已创建');
        }
        drawerOpen.value = false;
        await reload();
    }
    catch (e) { /* interceptor 已 toast */ }
}
async function onRemove(id) {
    await customersApi.remove(id);
    ElMessage.success('已删除');
    await reload();
}
function goDetail(id) { router.push(`/customers/${id}`); }
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
        placeholder: "搜索姓名/手机号",
        clearable: true,
        ...{ style: {} },
    }));
    const __VLS_10 = __VLS_9({
        ...{ 'onKeyup': {} },
        modelValue: (__VLS_ctx.search),
        placeholder: "搜索姓名/手机号",
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
    const __VLS_24 = {}.ElButton;
    /** @type {[typeof __VLS_components.ElButton, typeof __VLS_components.elButton, typeof __VLS_components.ElButton, typeof __VLS_components.elButton, ]} */ ;
    // @ts-ignore
    const __VLS_25 = __VLS_asFunctionalComponent(__VLS_24, new __VLS_24({
        ...{ 'onClick': {} },
        type: "primary",
    }));
    const __VLS_26 = __VLS_25({
        ...{ 'onClick': {} },
        type: "primary",
    }, ...__VLS_functionalComponentArgsRest(__VLS_25));
    let __VLS_28;
    let __VLS_29;
    let __VLS_30;
    const __VLS_31 = {
        onClick: (__VLS_ctx.openCreate)
    };
    __VLS_27.slots.default;
    var __VLS_27;
}
const __VLS_32 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_33 = __VLS_asFunctionalComponent(__VLS_32, new __VLS_32({
    prop: "name",
    label: "姓名",
}));
const __VLS_34 = __VLS_33({
    prop: "name",
    label: "姓名",
}, ...__VLS_functionalComponentArgsRest(__VLS_33));
const __VLS_36 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_37 = __VLS_asFunctionalComponent(__VLS_36, new __VLS_36({
    prop: "phone",
    label: "手机号",
}));
const __VLS_38 = __VLS_37({
    prop: "phone",
    label: "手机号",
}, ...__VLS_functionalComponentArgsRest(__VLS_37));
const __VLS_40 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_41 = __VLS_asFunctionalComponent(__VLS_40, new __VLS_40({
    prop: "ltv",
    label: "LTV",
}));
const __VLS_42 = __VLS_41({
    prop: "ltv",
    label: "LTV",
}, ...__VLS_functionalComponentArgsRest(__VLS_41));
const __VLS_44 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_45 = __VLS_asFunctionalComponent(__VLS_44, new __VLS_44({
    prop: "churn_score",
    label: "流失概率",
}));
const __VLS_46 = __VLS_45({
    prop: "churn_score",
    label: "流失概率",
}, ...__VLS_functionalComponentArgsRest(__VLS_45));
const __VLS_48 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_49 = __VLS_asFunctionalComponent(__VLS_48, new __VLS_48({
    prop: "segment",
    label: "分群",
}));
const __VLS_50 = __VLS_49({
    prop: "segment",
    label: "分群",
}, ...__VLS_functionalComponentArgsRest(__VLS_49));
const __VLS_52 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_53 = __VLS_asFunctionalComponent(__VLS_52, new __VLS_52({
    label: "操作",
    width: "220",
}));
const __VLS_54 = __VLS_53({
    label: "操作",
    width: "220",
}, ...__VLS_functionalComponentArgsRest(__VLS_53));
__VLS_55.slots.default;
{
    const { default: __VLS_thisSlot } = __VLS_55.slots;
    const [{ row }] = __VLS_getSlotParams(__VLS_thisSlot);
    const __VLS_56 = {}.ElButton;
    /** @type {[typeof __VLS_components.ElButton, typeof __VLS_components.elButton, typeof __VLS_components.ElButton, typeof __VLS_components.elButton, ]} */ ;
    // @ts-ignore
    const __VLS_57 = __VLS_asFunctionalComponent(__VLS_56, new __VLS_56({
        ...{ 'onClick': {} },
        text: true,
        type: "primary",
    }));
    const __VLS_58 = __VLS_57({
        ...{ 'onClick': {} },
        text: true,
        type: "primary",
    }, ...__VLS_functionalComponentArgsRest(__VLS_57));
    let __VLS_60;
    let __VLS_61;
    let __VLS_62;
    const __VLS_63 = {
        onClick: (...[$event]) => {
            __VLS_ctx.goDetail(row.customer_id);
        }
    };
    __VLS_59.slots.default;
    var __VLS_59;
    const __VLS_64 = {}.ElButton;
    /** @type {[typeof __VLS_components.ElButton, typeof __VLS_components.elButton, typeof __VLS_components.ElButton, typeof __VLS_components.elButton, ]} */ ;
    // @ts-ignore
    const __VLS_65 = __VLS_asFunctionalComponent(__VLS_64, new __VLS_64({
        ...{ 'onClick': {} },
        text: true,
        type: "primary",
    }));
    const __VLS_66 = __VLS_65({
        ...{ 'onClick': {} },
        text: true,
        type: "primary",
    }, ...__VLS_functionalComponentArgsRest(__VLS_65));
    let __VLS_68;
    let __VLS_69;
    let __VLS_70;
    const __VLS_71 = {
        onClick: (...[$event]) => {
            __VLS_ctx.openEdit(row);
        }
    };
    __VLS_67.slots.default;
    var __VLS_67;
    const __VLS_72 = {}.ElPopconfirm;
    /** @type {[typeof __VLS_components.ElPopconfirm, typeof __VLS_components.elPopconfirm, typeof __VLS_components.ElPopconfirm, typeof __VLS_components.elPopconfirm, ]} */ ;
    // @ts-ignore
    const __VLS_73 = __VLS_asFunctionalComponent(__VLS_72, new __VLS_72({
        ...{ 'onConfirm': {} },
        title: "确认删除?",
    }));
    const __VLS_74 = __VLS_73({
        ...{ 'onConfirm': {} },
        title: "确认删除?",
    }, ...__VLS_functionalComponentArgsRest(__VLS_73));
    let __VLS_76;
    let __VLS_77;
    let __VLS_78;
    const __VLS_79 = {
        onConfirm: (...[$event]) => {
            __VLS_ctx.onRemove(row.customer_id);
        }
    };
    __VLS_75.slots.default;
    {
        const { reference: __VLS_thisSlot } = __VLS_75.slots;
        const __VLS_80 = {}.ElButton;
        /** @type {[typeof __VLS_components.ElButton, typeof __VLS_components.elButton, typeof __VLS_components.ElButton, typeof __VLS_components.elButton, ]} */ ;
        // @ts-ignore
        const __VLS_81 = __VLS_asFunctionalComponent(__VLS_80, new __VLS_80({
            text: true,
            type: "danger",
        }));
        const __VLS_82 = __VLS_81({
            text: true,
            type: "danger",
        }, ...__VLS_functionalComponentArgsRest(__VLS_81));
        __VLS_83.slots.default;
        var __VLS_83;
    }
    var __VLS_75;
}
var __VLS_55;
var __VLS_2;
/** @type {[typeof FormDrawer, typeof FormDrawer, ]} */ ;
// @ts-ignore
const __VLS_84 = __VLS_asFunctionalComponent(FormDrawer, new FormDrawer({
    ...{ 'onSubmit': {} },
    modelValue: (__VLS_ctx.drawerOpen),
    title: (__VLS_ctx.editing ? '编辑客户' : '新建客户'),
    form: (__VLS_ctx.form),
}));
const __VLS_85 = __VLS_84({
    ...{ 'onSubmit': {} },
    modelValue: (__VLS_ctx.drawerOpen),
    title: (__VLS_ctx.editing ? '编辑客户' : '新建客户'),
    form: (__VLS_ctx.form),
}, ...__VLS_functionalComponentArgsRest(__VLS_84));
let __VLS_87;
let __VLS_88;
let __VLS_89;
const __VLS_90 = {
    onSubmit: (__VLS_ctx.onSubmit)
};
__VLS_86.slots.default;
{
    const { default: __VLS_thisSlot } = __VLS_86.slots;
    const [{ form }] = __VLS_getSlotParams(__VLS_thisSlot);
    const __VLS_91 = {}.ElFormItem;
    /** @type {[typeof __VLS_components.ElFormItem, typeof __VLS_components.elFormItem, typeof __VLS_components.ElFormItem, typeof __VLS_components.elFormItem, ]} */ ;
    // @ts-ignore
    const __VLS_92 = __VLS_asFunctionalComponent(__VLS_91, new __VLS_91({
        label: "姓名",
        required: true,
    }));
    const __VLS_93 = __VLS_92({
        label: "姓名",
        required: true,
    }, ...__VLS_functionalComponentArgsRest(__VLS_92));
    __VLS_94.slots.default;
    const __VLS_95 = {}.ElInput;
    /** @type {[typeof __VLS_components.ElInput, typeof __VLS_components.elInput, ]} */ ;
    // @ts-ignore
    const __VLS_96 = __VLS_asFunctionalComponent(__VLS_95, new __VLS_95({
        modelValue: (form.name),
    }));
    const __VLS_97 = __VLS_96({
        modelValue: (form.name),
    }, ...__VLS_functionalComponentArgsRest(__VLS_96));
    var __VLS_94;
    const __VLS_99 = {}.ElFormItem;
    /** @type {[typeof __VLS_components.ElFormItem, typeof __VLS_components.elFormItem, typeof __VLS_components.ElFormItem, typeof __VLS_components.elFormItem, ]} */ ;
    // @ts-ignore
    const __VLS_100 = __VLS_asFunctionalComponent(__VLS_99, new __VLS_99({
        label: "手机号",
    }));
    const __VLS_101 = __VLS_100({
        label: "手机号",
    }, ...__VLS_functionalComponentArgsRest(__VLS_100));
    __VLS_102.slots.default;
    const __VLS_103 = {}.ElInput;
    /** @type {[typeof __VLS_components.ElInput, typeof __VLS_components.elInput, ]} */ ;
    // @ts-ignore
    const __VLS_104 = __VLS_asFunctionalComponent(__VLS_103, new __VLS_103({
        modelValue: (form.phone),
    }));
    const __VLS_105 = __VLS_104({
        modelValue: (form.phone),
    }, ...__VLS_functionalComponentArgsRest(__VLS_104));
    var __VLS_102;
}
var __VLS_86;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            DataTable: DataTable,
            FormDrawer: FormDrawer,
            items: items,
            total: total,
            loading: loading,
            page: page,
            pageSize: pageSize,
            search: search,
            drawerOpen: drawerOpen,
            editing: editing,
            form: form,
            reload: reload,
            openCreate: openCreate,
            openEdit: openEdit,
            onSubmit: onSubmit,
            onRemove: onRemove,
            goDetail: goDetail,
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