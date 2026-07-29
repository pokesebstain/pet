import { onMounted, ref } from 'vue';
import DataTable from '@/components/common/DataTable.vue';
import { http } from '@/api/client';
import { listPage } from '@/utils/http';
import { formatDateTime } from '@/utils/format';
const partners = ref([]);
const loadingPartners = ref(false);
const referrals = ref([]);
const referralTotal = ref(0);
const loadingReferrals = ref(false);
const page = ref(1);
const pageSize = ref(20);
async function reloadPartners() {
    loadingPartners.value = true;
    try {
        const { data } = await http.get('/ecosystem/partners');
        partners.value = data;
    }
    finally {
        loadingPartners.value = false;
    }
}
async function reloadReferrals() {
    loadingReferrals.value = true;
    try {
        const r = await listPage('/ecosystem/referrals', {
            page: page.value, page_size: pageSize.value
        });
        referrals.value = r.items;
        referralTotal.value = r.total;
    }
    finally {
        loadingReferrals.value = false;
    }
}
onMounted(() => {
    reloadPartners();
    reloadReferrals();
});
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
const __VLS_ctx = {};
let __VLS_components;
let __VLS_directives;
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({});
__VLS_asFunctionalElement(__VLS_intrinsicElements.h2, __VLS_intrinsicElements.h2)({});
__VLS_asFunctionalElement(__VLS_intrinsicElements.h3, __VLS_intrinsicElements.h3)({});
const __VLS_0 = {}.ElTable;
/** @type {[typeof __VLS_components.ElTable, typeof __VLS_components.elTable, typeof __VLS_components.ElTable, typeof __VLS_components.elTable, ]} */ ;
// @ts-ignore
const __VLS_1 = __VLS_asFunctionalComponent(__VLS_0, new __VLS_0({
    data: (__VLS_ctx.partners),
    border: true,
}));
const __VLS_2 = __VLS_1({
    data: (__VLS_ctx.partners),
    border: true,
}, ...__VLS_functionalComponentArgsRest(__VLS_1));
__VLS_asFunctionalDirective(__VLS_directives.vLoading)(null, { ...__VLS_directiveBindingRestFields, value: (__VLS_ctx.loadingPartners) }, null, null);
__VLS_3.slots.default;
const __VLS_4 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_5 = __VLS_asFunctionalComponent(__VLS_4, new __VLS_4({
    prop: "partner_id",
    label: "ID",
}));
const __VLS_6 = __VLS_5({
    prop: "partner_id",
    label: "ID",
}, ...__VLS_functionalComponentArgsRest(__VLS_5));
const __VLS_8 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_9 = __VLS_asFunctionalComponent(__VLS_8, new __VLS_8({
    prop: "name",
    label: "名称",
}));
const __VLS_10 = __VLS_9({
    prop: "name",
    label: "名称",
}, ...__VLS_functionalComponentArgsRest(__VLS_9));
const __VLS_12 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_13 = __VLS_asFunctionalComponent(__VLS_12, new __VLS_12({
    prop: "address",
    label: "地址",
}));
const __VLS_14 = __VLS_13({
    prop: "address",
    label: "地址",
}, ...__VLS_functionalComponentArgsRest(__VLS_13));
const __VLS_16 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_17 = __VLS_asFunctionalComponent(__VLS_16, new __VLS_16({
    prop: "phone",
    label: "电话",
}));
const __VLS_18 = __VLS_17({
    prop: "phone",
    label: "电话",
}, ...__VLS_functionalComponentArgsRest(__VLS_17));
const __VLS_20 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_21 = __VLS_asFunctionalComponent(__VLS_20, new __VLS_20({
    prop: "specialties",
    label: "擅长",
}));
const __VLS_22 = __VLS_21({
    prop: "specialties",
    label: "擅长",
}, ...__VLS_functionalComponentArgsRest(__VLS_21));
__VLS_23.slots.default;
{
    const { default: __VLS_thisSlot } = __VLS_23.slots;
    const [{ row }] = __VLS_getSlotParams(__VLS_thisSlot);
    for (const [s] of __VLS_getVForSourceType((row.specialties))) {
        const __VLS_24 = {}.ElTag;
        /** @type {[typeof __VLS_components.ElTag, typeof __VLS_components.elTag, typeof __VLS_components.ElTag, typeof __VLS_components.elTag, ]} */ ;
        // @ts-ignore
        const __VLS_25 = __VLS_asFunctionalComponent(__VLS_24, new __VLS_24({
            key: (s),
            size: "small",
            ...{ style: {} },
        }));
        const __VLS_26 = __VLS_25({
            key: (s),
            size: "small",
            ...{ style: {} },
        }, ...__VLS_functionalComponentArgsRest(__VLS_25));
        __VLS_27.slots.default;
        (s);
        var __VLS_27;
    }
}
var __VLS_23;
var __VLS_3;
__VLS_asFunctionalElement(__VLS_intrinsicElements.h3, __VLS_intrinsicElements.h3)({
    ...{ style: {} },
});
/** @type {[typeof DataTable, typeof DataTable, ]} */ ;
// @ts-ignore
const __VLS_28 = __VLS_asFunctionalComponent(DataTable, new DataTable({
    ...{ 'onPageChange': {} },
    ...{ 'onSizeChange': {} },
    items: (__VLS_ctx.referrals),
    total: (__VLS_ctx.referralTotal),
    loading: (__VLS_ctx.loadingReferrals),
}));
const __VLS_29 = __VLS_28({
    ...{ 'onPageChange': {} },
    ...{ 'onSizeChange': {} },
    items: (__VLS_ctx.referrals),
    total: (__VLS_ctx.referralTotal),
    loading: (__VLS_ctx.loadingReferrals),
}, ...__VLS_functionalComponentArgsRest(__VLS_28));
let __VLS_31;
let __VLS_32;
let __VLS_33;
const __VLS_34 = {
    onPageChange: ((p) => { __VLS_ctx.page = p; __VLS_ctx.reloadReferrals(); })
};
const __VLS_35 = {
    onSizeChange: ((s) => { __VLS_ctx.pageSize = s; __VLS_ctx.reloadReferrals(); })
};
__VLS_30.slots.default;
const __VLS_36 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_37 = __VLS_asFunctionalComponent(__VLS_36, new __VLS_36({
    prop: "referral_id",
    label: "ID",
}));
const __VLS_38 = __VLS_37({
    prop: "referral_id",
    label: "ID",
}, ...__VLS_functionalComponentArgsRest(__VLS_37));
const __VLS_40 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_41 = __VLS_asFunctionalComponent(__VLS_40, new __VLS_40({
    prop: "customer_id",
    label: "客户",
}));
const __VLS_42 = __VLS_41({
    prop: "customer_id",
    label: "客户",
}, ...__VLS_functionalComponentArgsRest(__VLS_41));
const __VLS_44 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_45 = __VLS_asFunctionalComponent(__VLS_44, new __VLS_44({
    prop: "pet_id",
    label: "宠物",
}));
const __VLS_46 = __VLS_45({
    prop: "pet_id",
    label: "宠物",
}, ...__VLS_functionalComponentArgsRest(__VLS_45));
const __VLS_48 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_49 = __VLS_asFunctionalComponent(__VLS_48, new __VLS_48({
    prop: "partner_id",
    label: "医院",
}));
const __VLS_50 = __VLS_49({
    prop: "partner_id",
    label: "医院",
}, ...__VLS_functionalComponentArgsRest(__VLS_49));
const __VLS_52 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_53 = __VLS_asFunctionalComponent(__VLS_52, new __VLS_52({
    prop: "status",
    label: "状态",
}));
const __VLS_54 = __VLS_53({
    prop: "status",
    label: "状态",
}, ...__VLS_functionalComponentArgsRest(__VLS_53));
__VLS_55.slots.default;
{
    const { default: __VLS_thisSlot } = __VLS_55.slots;
    const [{ row }] = __VLS_getSlotParams(__VLS_thisSlot);
    const __VLS_56 = {}.ElTag;
    /** @type {[typeof __VLS_components.ElTag, typeof __VLS_components.elTag, typeof __VLS_components.ElTag, typeof __VLS_components.elTag, ]} */ ;
    // @ts-ignore
    const __VLS_57 = __VLS_asFunctionalComponent(__VLS_56, new __VLS_56({
        type: (row.status === 'completed' ? 'success' : 'warning'),
    }));
    const __VLS_58 = __VLS_57({
        type: (row.status === 'completed' ? 'success' : 'warning'),
    }, ...__VLS_functionalComponentArgsRest(__VLS_57));
    __VLS_59.slots.default;
    (row.status);
    var __VLS_59;
}
var __VLS_55;
const __VLS_60 = {}.ElTableColumn;
/** @type {[typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ]} */ ;
// @ts-ignore
const __VLS_61 = __VLS_asFunctionalComponent(__VLS_60, new __VLS_60({
    prop: "created_at",
    label: "创建时间",
}));
const __VLS_62 = __VLS_61({
    prop: "created_at",
    label: "创建时间",
}, ...__VLS_functionalComponentArgsRest(__VLS_61));
__VLS_63.slots.default;
{
    const { default: __VLS_thisSlot } = __VLS_63.slots;
    const [{ row }] = __VLS_getSlotParams(__VLS_thisSlot);
    (__VLS_ctx.formatDateTime(row.created_at));
}
var __VLS_63;
var __VLS_30;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            DataTable: DataTable,
            formatDateTime: formatDateTime,
            partners: partners,
            loadingPartners: loadingPartners,
            referrals: referrals,
            referralTotal: referralTotal,
            loadingReferrals: loadingReferrals,
            page: page,
            pageSize: pageSize,
            reloadReferrals: reloadReferrals,
        };
    },
});
export default (await import('vue')).defineComponent({
    setup() {
        return {};
    },
});
; /* PartiallyEnd: #4569/main.vue */
//# sourceMappingURL=PartnersView.vue.js.map