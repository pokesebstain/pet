import { onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { http } from '@/api/client';
import FormDrawer from '@/components/common/FormDrawer.vue';
const items = ref([]);
const loading = ref(false);
const drawerOpen = ref(false);
const form = reactive({ name: '', capacity: 1, is_active: true });
const editingId = ref(null);
async function reload() {
    loading.value = true;
    try {
        const { data } = await http.get('/resources');
        items.value = data;
    }
    finally {
        loading.value = false;
    }
}
function openEdit(row) {
    editingId.value = row.resource_id;
    form.name = row.name;
    form.capacity = row.capacity;
    form.is_active = row.is_active;
    drawerOpen.value = true;
}
async function onSubmit() {
    await http.put(`/resources/${editingId.value}`, { ...form });
    ElMessage.success('已保存');
    drawerOpen.value = false;
    await reload();
}
onMounted(reload);
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
const __VLS_ctx = {};
let __VLS_components;
let __VLS_directives;
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({});
__VLS_asFunctionalElement(__VLS_intrinsicElements.h2, __VLS_intrinsicElements.h2)({});
const __VLS_0 = {}.ElAlert;
/** @type {[typeof __VLS_components.ElAlert, typeof __VLS_components.elAlert, typeof __VLS_components.ElAlert, typeof __VLS_components.elAlert, ]} */ ;
// @ts-ignore
const __VLS_1 = __VLS_asFunctionalComponent(__VLS_0, new __VLS_0({
    type: "info",
    closable: (false),
    ...{ style: {} },
}));
const __VLS_2 = __VLS_1({
    type: "info",
    closable: (false),
    ...{ style: {} },
}, ...__VLS_functionalComponentArgsRest(__VLS_1));
__VLS_3.slots.default;
var __VLS_3;
const __VLS_4 = {}.ElTable;
/** @type {[typeof __VLS_components.ElTable, typeof __VLS_components.elTable, typeof __VLS_components.ElTable, typeof __VLS_components.elTable, ]} */ ;
// @ts-ignore
const __VLS_5 = __VLS_asFunctionalComponent(__VLS_4, new __VLS_4({
    data: (__VLS_ctx.items),
    border: true,
}));
const __VLS_6 = __VLS_5({
    data: (__VLS_ctx.items),
    border: true,
}, ...__VLS_functionalComponentArgsRest(__VLS_5));
__VLS_asFunctionalDirective(__VLS_directives.vLoading)(null, { ...__VLS_directiveBindingRestFields, value: (__VLS_ctx.loading) }, null, null);
__VLS_7.slots.default;
const __VLS_8 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_9 = __VLS_asFunctionalComponent(__VLS_8, new __VLS_8({
    prop: "resource_id",
    label: "ID",
}));
const __VLS_10 = __VLS_9({
    prop: "resource_id",
    label: "ID",
}, ...__VLS_functionalComponentArgsRest(__VLS_9));
const __VLS_12 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_13 = __VLS_asFunctionalComponent(__VLS_12, new __VLS_12({
    prop: "name",
    label: "名称",
}));
const __VLS_14 = __VLS_13({
    prop: "name",
    label: "名称",
}, ...__VLS_functionalComponentArgsRest(__VLS_13));
const __VLS_16 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_17 = __VLS_asFunctionalComponent(__VLS_16, new __VLS_16({
    prop: "capacity",
    label: "容量",
}));
const __VLS_18 = __VLS_17({
    prop: "capacity",
    label: "容量",
}, ...__VLS_functionalComponentArgsRest(__VLS_17));
const __VLS_20 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_21 = __VLS_asFunctionalComponent(__VLS_20, new __VLS_20({
    prop: "is_active",
    label: "启用",
}));
const __VLS_22 = __VLS_21({
    prop: "is_active",
    label: "启用",
}, ...__VLS_functionalComponentArgsRest(__VLS_21));
__VLS_23.slots.default;
{
    const { default: __VLS_thisSlot } = __VLS_23.slots;
    const [{ row }] = __VLS_getSlotParams(__VLS_thisSlot);
    if (row.is_active) {
        const __VLS_24 = {}.ElTag;
        /** @type {[typeof __VLS_components.ElTag, typeof __VLS_components.elTag, typeof __VLS_components.ElTag, typeof __VLS_components.elTag, ]} */ ;
        // @ts-ignore
        const __VLS_25 = __VLS_asFunctionalComponent(__VLS_24, new __VLS_24({
            type: "success",
        }));
        const __VLS_26 = __VLS_25({
            type: "success",
        }, ...__VLS_functionalComponentArgsRest(__VLS_25));
        __VLS_27.slots.default;
        var __VLS_27;
    }
    else {
        const __VLS_28 = {}.ElTag;
        /** @type {[typeof __VLS_components.ElTag, typeof __VLS_components.elTag, typeof __VLS_components.ElTag, typeof __VLS_components.elTag, ]} */ ;
        // @ts-ignore
        const __VLS_29 = __VLS_asFunctionalComponent(__VLS_28, new __VLS_28({
            type: "info",
        }));
        const __VLS_30 = __VLS_29({
            type: "info",
        }, ...__VLS_functionalComponentArgsRest(__VLS_29));
        __VLS_31.slots.default;
        var __VLS_31;
    }
}
var __VLS_23;
const __VLS_32 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_33 = __VLS_asFunctionalComponent(__VLS_32, new __VLS_32({
    label: "操作",
    width: "120",
}));
const __VLS_34 = __VLS_33({
    label: "操作",
    width: "120",
}, ...__VLS_functionalComponentArgsRest(__VLS_33));
__VLS_35.slots.default;
{
    const { default: __VLS_thisSlot } = __VLS_35.slots;
    const [{ row }] = __VLS_getSlotParams(__VLS_thisSlot);
    const __VLS_36 = {}.ElButton;
    /** @type {[typeof __VLS_components.ElButton, typeof __VLS_components.elButton, typeof __VLS_components.ElButton, typeof __VLS_components.elButton, ]} */ ;
    // @ts-ignore
    const __VLS_37 = __VLS_asFunctionalComponent(__VLS_36, new __VLS_36({
        ...{ 'onClick': {} },
        text: true,
        type: "primary",
    }));
    const __VLS_38 = __VLS_37({
        ...{ 'onClick': {} },
        text: true,
        type: "primary",
    }, ...__VLS_functionalComponentArgsRest(__VLS_37));
    let __VLS_40;
    let __VLS_41;
    let __VLS_42;
    const __VLS_43 = {
        onClick: (...[$event]) => {
            __VLS_ctx.openEdit(row);
        }
    };
    __VLS_39.slots.default;
    var __VLS_39;
}
var __VLS_35;
var __VLS_7;
/** @type {[typeof FormDrawer, typeof FormDrawer, ]} */ ;
// @ts-ignore
const __VLS_44 = __VLS_asFunctionalComponent(FormDrawer, new FormDrawer({
    ...{ 'onSubmit': {} },
    modelValue: (__VLS_ctx.drawerOpen),
    title: "编辑资源",
    form: (__VLS_ctx.form),
}));
const __VLS_45 = __VLS_44({
    ...{ 'onSubmit': {} },
    modelValue: (__VLS_ctx.drawerOpen),
    title: "编辑资源",
    form: (__VLS_ctx.form),
}, ...__VLS_functionalComponentArgsRest(__VLS_44));
let __VLS_47;
let __VLS_48;
let __VLS_49;
const __VLS_50 = {
    onSubmit: (__VLS_ctx.onSubmit)
};
__VLS_46.slots.default;
{
    const { default: __VLS_thisSlot } = __VLS_46.slots;
    const [{ form }] = __VLS_getSlotParams(__VLS_thisSlot);
    const __VLS_51 = {}.ElFormItem;
    /** @type {[typeof __VLS_components.ElFormItem, typeof __VLS_components.elFormItem, typeof __VLS_components.ElFormItem, typeof __VLS_components.elFormItem, ]} */ ;
    // @ts-ignore
    const __VLS_52 = __VLS_asFunctionalComponent(__VLS_51, new __VLS_51({
        label: "名称",
    }));
    const __VLS_53 = __VLS_52({
        label: "名称",
    }, ...__VLS_functionalComponentArgsRest(__VLS_52));
    __VLS_54.slots.default;
    const __VLS_55 = {}.ElInput;
    /** @type {[typeof __VLS_components.ElInput, typeof __VLS_components.elInput, ]} */ ;
    // @ts-ignore
    const __VLS_56 = __VLS_asFunctionalComponent(__VLS_55, new __VLS_55({
        modelValue: (form.name),
    }));
    const __VLS_57 = __VLS_56({
        modelValue: (form.name),
    }, ...__VLS_functionalComponentArgsRest(__VLS_56));
    var __VLS_54;
    const __VLS_59 = {}.ElFormItem;
    /** @type {[typeof __VLS_components.ElFormItem, typeof __VLS_components.elFormItem, typeof __VLS_components.ElFormItem, typeof __VLS_components.elFormItem, ]} */ ;
    // @ts-ignore
    const __VLS_60 = __VLS_asFunctionalComponent(__VLS_59, new __VLS_59({
        label: "容量",
    }));
    const __VLS_61 = __VLS_60({
        label: "容量",
    }, ...__VLS_functionalComponentArgsRest(__VLS_60));
    __VLS_62.slots.default;
    const __VLS_63 = {}.ElInputNumber;
    /** @type {[typeof __VLS_components.ElInputNumber, typeof __VLS_components.elInputNumber, ]} */ ;
    // @ts-ignore
    const __VLS_64 = __VLS_asFunctionalComponent(__VLS_63, new __VLS_63({
        modelValue: (form.capacity),
        min: (1),
    }));
    const __VLS_65 = __VLS_64({
        modelValue: (form.capacity),
        min: (1),
    }, ...__VLS_functionalComponentArgsRest(__VLS_64));
    var __VLS_62;
    const __VLS_67 = {}.ElFormItem;
    /** @type {[typeof __VLS_components.ElFormItem, typeof __VLS_components.elFormItem, typeof __VLS_components.ElFormItem, typeof __VLS_components.elFormItem, ]} */ ;
    // @ts-ignore
    const __VLS_68 = __VLS_asFunctionalComponent(__VLS_67, new __VLS_67({
        label: "启用",
    }));
    const __VLS_69 = __VLS_68({
        label: "启用",
    }, ...__VLS_functionalComponentArgsRest(__VLS_68));
    __VLS_70.slots.default;
    const __VLS_71 = {}.ElSwitch;
    /** @type {[typeof __VLS_components.ElSwitch, typeof __VLS_components.elSwitch, ]} */ ;
    // @ts-ignore
    const __VLS_72 = __VLS_asFunctionalComponent(__VLS_71, new __VLS_71({
        modelValue: (form.is_active),
    }));
    const __VLS_73 = __VLS_72({
        modelValue: (form.is_active),
    }, ...__VLS_functionalComponentArgsRest(__VLS_72));
    var __VLS_70;
}
var __VLS_46;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            FormDrawer: FormDrawer,
            items: items,
            loading: loading,
            drawerOpen: drawerOpen,
            form: form,
            openEdit: openEdit,
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
//# sourceMappingURL=View.vue.js.map