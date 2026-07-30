import { useRoute } from 'vue-router';
import { useAppStore } from '@/stores/app';
import { computed } from 'vue';
import { Histogram, User, TrendCharts, DataAnalysis, Box, Document } from '@element-plus/icons-vue';
const route = useRoute();
const app = useAppStore();
const collapsed = computed(() => app.sidebarCollapsed);
// 根据当前路径展开对应分组，使刷新页面 / 直接跳转时不会所有分组都收起。
const GROUP_PREFIXES = {
    '/customers': 'group-customer',
    '/pets': 'group-customer',
    '/appointments': 'group-customer',
    '/business-hours': 'group-customer',
    '/resources': 'group-customer',
    '/health': 'group-health',
    '/operations': 'group-growth',
    '/marketing': 'group-growth',
    '/subscriptions': 'group-growth',
    '/supply': 'group-supply',
    '/ecosystem': 'group-supply'
};
const defaultOpeneds = computed(() => {
    const match = Object.entries(GROUP_PREFIXES).find(([prefix]) => route.path.startsWith(prefix));
    return match ? [match[1]] : [];
});
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
const __VLS_ctx = {};
let __VLS_components;
let __VLS_directives;
/** @type {__VLS_StyleScopedClasses['sidebar']} */ ;
/** @type {__VLS_StyleScopedClasses['sidebar']} */ ;
/** @type {__VLS_StyleScopedClasses['sidebar']} */ ;
/** @type {__VLS_StyleScopedClasses['sidebar']} */ ;
/** @type {__VLS_StyleScopedClasses['el-menu-item']} */ ;
/** @type {__VLS_StyleScopedClasses['sidebar']} */ ;
/** @type {__VLS_StyleScopedClasses['el-sub-menu__title']} */ ;
/** @type {__VLS_StyleScopedClasses['sidebar']} */ ;
/** @type {__VLS_StyleScopedClasses['el-menu-item']} */ ;
/** @type {__VLS_StyleScopedClasses['sidebar']} */ ;
/** @type {__VLS_StyleScopedClasses['el-menu-item']} */ ;
// CSS variable injection 
// CSS variable injection end 
const __VLS_0 = {}.ElAside;
/** @type {[typeof __VLS_components.ElAside, typeof __VLS_components.elAside, typeof __VLS_components.ElAside, typeof __VLS_components.elAside, ]} */ ;
// @ts-ignore
const __VLS_1 = __VLS_asFunctionalComponent(__VLS_0, new __VLS_0({
    width: (__VLS_ctx.collapsed ? '64px' : '220px'),
    ...{ class: "sidebar" },
}));
const __VLS_2 = __VLS_1({
    width: (__VLS_ctx.collapsed ? '64px' : '220px'),
    ...{ class: "sidebar" },
}, ...__VLS_functionalComponentArgsRest(__VLS_1));
var __VLS_4 = {};
__VLS_3.slots.default;
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "sidebar__brand" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.span)({
    ...{ class: "sidebar__brand-dot" },
});
if (!__VLS_ctx.collapsed) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: "sidebar__brand-text" },
    });
}
const __VLS_5 = {}.ElMenu;
/** @type {[typeof __VLS_components.ElMenu, typeof __VLS_components.elMenu, typeof __VLS_components.ElMenu, typeof __VLS_components.elMenu, ]} */ ;
// @ts-ignore
const __VLS_6 = __VLS_asFunctionalComponent(__VLS_5, new __VLS_5({
    defaultActive: (__VLS_ctx.route.path),
    defaultOpeneds: (__VLS_ctx.defaultOpeneds),
    router: true,
    collapse: (__VLS_ctx.collapsed),
    uniqueOpened: true,
    ...{ class: "sidebar__menu" },
}));
const __VLS_7 = __VLS_6({
    defaultActive: (__VLS_ctx.route.path),
    defaultOpeneds: (__VLS_ctx.defaultOpeneds),
    router: true,
    collapse: (__VLS_ctx.collapsed),
    uniqueOpened: true,
    ...{ class: "sidebar__menu" },
}, ...__VLS_functionalComponentArgsRest(__VLS_6));
__VLS_8.slots.default;
const __VLS_9 = {}.ElMenuItem;
/** @type {[typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, ]} */ ;
// @ts-ignore
const __VLS_10 = __VLS_asFunctionalComponent(__VLS_9, new __VLS_9({
    index: "/dashboard",
    route: ({ path: '/dashboard' }),
}));
const __VLS_11 = __VLS_10({
    index: "/dashboard",
    route: ({ path: '/dashboard' }),
}, ...__VLS_functionalComponentArgsRest(__VLS_10));
__VLS_12.slots.default;
const __VLS_13 = {}.ElIcon;
/** @type {[typeof __VLS_components.ElIcon, typeof __VLS_components.elIcon, typeof __VLS_components.ElIcon, typeof __VLS_components.elIcon, ]} */ ;
// @ts-ignore
const __VLS_14 = __VLS_asFunctionalComponent(__VLS_13, new __VLS_13({}));
const __VLS_15 = __VLS_14({}, ...__VLS_functionalComponentArgsRest(__VLS_14));
__VLS_16.slots.default;
const __VLS_17 = {}.Histogram;
/** @type {[typeof __VLS_components.Histogram, ]} */ ;
// @ts-ignore
const __VLS_18 = __VLS_asFunctionalComponent(__VLS_17, new __VLS_17({}));
const __VLS_19 = __VLS_18({}, ...__VLS_functionalComponentArgsRest(__VLS_18));
var __VLS_16;
{
    const { title: __VLS_thisSlot } = __VLS_12.slots;
}
var __VLS_12;
const __VLS_21 = {}.ElSubMenu;
/** @type {[typeof __VLS_components.ElSubMenu, typeof __VLS_components.elSubMenu, typeof __VLS_components.ElSubMenu, typeof __VLS_components.elSubMenu, ]} */ ;
// @ts-ignore
const __VLS_22 = __VLS_asFunctionalComponent(__VLS_21, new __VLS_21({
    index: "group-customer",
}));
const __VLS_23 = __VLS_22({
    index: "group-customer",
}, ...__VLS_functionalComponentArgsRest(__VLS_22));
__VLS_24.slots.default;
{
    const { title: __VLS_thisSlot } = __VLS_24.slots;
    const __VLS_25 = {}.ElIcon;
    /** @type {[typeof __VLS_components.ElIcon, typeof __VLS_components.elIcon, typeof __VLS_components.ElIcon, typeof __VLS_components.elIcon, ]} */ ;
    // @ts-ignore
    const __VLS_26 = __VLS_asFunctionalComponent(__VLS_25, new __VLS_25({}));
    const __VLS_27 = __VLS_26({}, ...__VLS_functionalComponentArgsRest(__VLS_26));
    __VLS_28.slots.default;
    const __VLS_29 = {}.User;
    /** @type {[typeof __VLS_components.User, ]} */ ;
    // @ts-ignore
    const __VLS_30 = __VLS_asFunctionalComponent(__VLS_29, new __VLS_29({}));
    const __VLS_31 = __VLS_30({}, ...__VLS_functionalComponentArgsRest(__VLS_30));
    var __VLS_28;
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({});
}
const __VLS_33 = {}.ElMenuItem;
/** @type {[typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, ]} */ ;
// @ts-ignore
const __VLS_34 = __VLS_asFunctionalComponent(__VLS_33, new __VLS_33({
    index: "/customers",
    route: ({ path: '/customers' }),
}));
const __VLS_35 = __VLS_34({
    index: "/customers",
    route: ({ path: '/customers' }),
}, ...__VLS_functionalComponentArgsRest(__VLS_34));
__VLS_36.slots.default;
var __VLS_36;
const __VLS_37 = {}.ElMenuItem;
/** @type {[typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, ]} */ ;
// @ts-ignore
const __VLS_38 = __VLS_asFunctionalComponent(__VLS_37, new __VLS_37({
    index: "/pets",
    route: ({ path: '/pets' }),
}));
const __VLS_39 = __VLS_38({
    index: "/pets",
    route: ({ path: '/pets' }),
}, ...__VLS_functionalComponentArgsRest(__VLS_38));
__VLS_40.slots.default;
var __VLS_40;
const __VLS_41 = {}.ElMenuItem;
/** @type {[typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, ]} */ ;
// @ts-ignore
const __VLS_42 = __VLS_asFunctionalComponent(__VLS_41, new __VLS_41({
    index: "/appointments",
    route: ({ path: '/appointments' }),
}));
const __VLS_43 = __VLS_42({
    index: "/appointments",
    route: ({ path: '/appointments' }),
}, ...__VLS_functionalComponentArgsRest(__VLS_42));
__VLS_44.slots.default;
var __VLS_44;
const __VLS_45 = {}.ElMenuItem;
/** @type {[typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, ]} */ ;
// @ts-ignore
const __VLS_46 = __VLS_asFunctionalComponent(__VLS_45, new __VLS_45({
    index: "/business-hours",
    route: ({ path: '/business-hours' }),
}));
const __VLS_47 = __VLS_46({
    index: "/business-hours",
    route: ({ path: '/business-hours' }),
}, ...__VLS_functionalComponentArgsRest(__VLS_46));
__VLS_48.slots.default;
var __VLS_48;
const __VLS_49 = {}.ElMenuItem;
/** @type {[typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, ]} */ ;
// @ts-ignore
const __VLS_50 = __VLS_asFunctionalComponent(__VLS_49, new __VLS_49({
    index: "/resources",
    route: ({ path: '/resources' }),
}));
const __VLS_51 = __VLS_50({
    index: "/resources",
    route: ({ path: '/resources' }),
}, ...__VLS_functionalComponentArgsRest(__VLS_50));
__VLS_52.slots.default;
var __VLS_52;
var __VLS_24;
const __VLS_53 = {}.ElSubMenu;
/** @type {[typeof __VLS_components.ElSubMenu, typeof __VLS_components.elSubMenu, typeof __VLS_components.ElSubMenu, typeof __VLS_components.elSubMenu, ]} */ ;
// @ts-ignore
const __VLS_54 = __VLS_asFunctionalComponent(__VLS_53, new __VLS_53({
    index: "group-health",
}));
const __VLS_55 = __VLS_54({
    index: "group-health",
}, ...__VLS_functionalComponentArgsRest(__VLS_54));
__VLS_56.slots.default;
{
    const { title: __VLS_thisSlot } = __VLS_56.slots;
    const __VLS_57 = {}.ElIcon;
    /** @type {[typeof __VLS_components.ElIcon, typeof __VLS_components.elIcon, typeof __VLS_components.ElIcon, typeof __VLS_components.elIcon, ]} */ ;
    // @ts-ignore
    const __VLS_58 = __VLS_asFunctionalComponent(__VLS_57, new __VLS_57({}));
    const __VLS_59 = __VLS_58({}, ...__VLS_functionalComponentArgsRest(__VLS_58));
    __VLS_60.slots.default;
    const __VLS_61 = {}.TrendCharts;
    /** @type {[typeof __VLS_components.TrendCharts, ]} */ ;
    // @ts-ignore
    const __VLS_62 = __VLS_asFunctionalComponent(__VLS_61, new __VLS_61({}));
    const __VLS_63 = __VLS_62({}, ...__VLS_functionalComponentArgsRest(__VLS_62));
    var __VLS_60;
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({});
}
const __VLS_65 = {}.ElMenuItem;
/** @type {[typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, ]} */ ;
// @ts-ignore
const __VLS_66 = __VLS_asFunctionalComponent(__VLS_65, new __VLS_65({
    index: "/health/metrics",
    route: ({ path: '/health/metrics' }),
}));
const __VLS_67 = __VLS_66({
    index: "/health/metrics",
    route: ({ path: '/health/metrics' }),
}, ...__VLS_functionalComponentArgsRest(__VLS_66));
__VLS_68.slots.default;
var __VLS_68;
const __VLS_69 = {}.ElMenuItem;
/** @type {[typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, ]} */ ;
// @ts-ignore
const __VLS_70 = __VLS_asFunctionalComponent(__VLS_69, new __VLS_69({
    index: "/health/alerts",
    route: ({ path: '/health/alerts' }),
}));
const __VLS_71 = __VLS_70({
    index: "/health/alerts",
    route: ({ path: '/health/alerts' }),
}, ...__VLS_functionalComponentArgsRest(__VLS_70));
__VLS_72.slots.default;
var __VLS_72;
var __VLS_56;
const __VLS_73 = {}.ElSubMenu;
/** @type {[typeof __VLS_components.ElSubMenu, typeof __VLS_components.elSubMenu, typeof __VLS_components.ElSubMenu, typeof __VLS_components.elSubMenu, ]} */ ;
// @ts-ignore
const __VLS_74 = __VLS_asFunctionalComponent(__VLS_73, new __VLS_73({
    index: "group-growth",
}));
const __VLS_75 = __VLS_74({
    index: "group-growth",
}, ...__VLS_functionalComponentArgsRest(__VLS_74));
__VLS_76.slots.default;
{
    const { title: __VLS_thisSlot } = __VLS_76.slots;
    const __VLS_77 = {}.ElIcon;
    /** @type {[typeof __VLS_components.ElIcon, typeof __VLS_components.elIcon, typeof __VLS_components.ElIcon, typeof __VLS_components.elIcon, ]} */ ;
    // @ts-ignore
    const __VLS_78 = __VLS_asFunctionalComponent(__VLS_77, new __VLS_77({}));
    const __VLS_79 = __VLS_78({}, ...__VLS_functionalComponentArgsRest(__VLS_78));
    __VLS_80.slots.default;
    const __VLS_81 = {}.DataAnalysis;
    /** @type {[typeof __VLS_components.DataAnalysis, ]} */ ;
    // @ts-ignore
    const __VLS_82 = __VLS_asFunctionalComponent(__VLS_81, new __VLS_81({}));
    const __VLS_83 = __VLS_82({}, ...__VLS_functionalComponentArgsRest(__VLS_82));
    var __VLS_80;
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({});
}
const __VLS_85 = {}.ElMenuItem;
/** @type {[typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, ]} */ ;
// @ts-ignore
const __VLS_86 = __VLS_asFunctionalComponent(__VLS_85, new __VLS_85({
    index: "/operations/ltv",
    route: ({ path: '/operations/ltv' }),
}));
const __VLS_87 = __VLS_86({
    index: "/operations/ltv",
    route: ({ path: '/operations/ltv' }),
}, ...__VLS_functionalComponentArgsRest(__VLS_86));
__VLS_88.slots.default;
var __VLS_88;
const __VLS_89 = {}.ElMenuItem;
/** @type {[typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, ]} */ ;
// @ts-ignore
const __VLS_90 = __VLS_asFunctionalComponent(__VLS_89, new __VLS_89({
    index: "/operations/churn",
    route: ({ path: '/operations/churn' }),
}));
const __VLS_91 = __VLS_90({
    index: "/operations/churn",
    route: ({ path: '/operations/churn' }),
}, ...__VLS_functionalComponentArgsRest(__VLS_90));
__VLS_92.slots.default;
var __VLS_92;
const __VLS_93 = {}.ElMenuItem;
/** @type {[typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, ]} */ ;
// @ts-ignore
const __VLS_94 = __VLS_asFunctionalComponent(__VLS_93, new __VLS_93({
    index: "/marketing/contents",
    route: ({ path: '/marketing/contents' }),
}));
const __VLS_95 = __VLS_94({
    index: "/marketing/contents",
    route: ({ path: '/marketing/contents' }),
}, ...__VLS_functionalComponentArgsRest(__VLS_94));
__VLS_96.slots.default;
var __VLS_96;
const __VLS_97 = {}.ElMenuItem;
/** @type {[typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, ]} */ ;
// @ts-ignore
const __VLS_98 = __VLS_asFunctionalComponent(__VLS_97, new __VLS_97({
    index: "/subscriptions",
    route: ({ path: '/subscriptions' }),
}));
const __VLS_99 = __VLS_98({
    index: "/subscriptions",
    route: ({ path: '/subscriptions' }),
}, ...__VLS_functionalComponentArgsRest(__VLS_98));
__VLS_100.slots.default;
var __VLS_100;
var __VLS_76;
const __VLS_101 = {}.ElSubMenu;
/** @type {[typeof __VLS_components.ElSubMenu, typeof __VLS_components.elSubMenu, typeof __VLS_components.ElSubMenu, typeof __VLS_components.elSubMenu, ]} */ ;
// @ts-ignore
const __VLS_102 = __VLS_asFunctionalComponent(__VLS_101, new __VLS_101({
    index: "group-supply",
}));
const __VLS_103 = __VLS_102({
    index: "group-supply",
}, ...__VLS_functionalComponentArgsRest(__VLS_102));
__VLS_104.slots.default;
{
    const { title: __VLS_thisSlot } = __VLS_104.slots;
    const __VLS_105 = {}.ElIcon;
    /** @type {[typeof __VLS_components.ElIcon, typeof __VLS_components.elIcon, typeof __VLS_components.ElIcon, typeof __VLS_components.elIcon, ]} */ ;
    // @ts-ignore
    const __VLS_106 = __VLS_asFunctionalComponent(__VLS_105, new __VLS_105({}));
    const __VLS_107 = __VLS_106({}, ...__VLS_functionalComponentArgsRest(__VLS_106));
    __VLS_108.slots.default;
    const __VLS_109 = {}.Box;
    /** @type {[typeof __VLS_components.Box, ]} */ ;
    // @ts-ignore
    const __VLS_110 = __VLS_asFunctionalComponent(__VLS_109, new __VLS_109({}));
    const __VLS_111 = __VLS_110({}, ...__VLS_functionalComponentArgsRest(__VLS_110));
    var __VLS_108;
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({});
}
const __VLS_113 = {}.ElMenuItem;
/** @type {[typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, ]} */ ;
// @ts-ignore
const __VLS_114 = __VLS_asFunctionalComponent(__VLS_113, new __VLS_113({
    index: "/supply/skus",
    route: ({ path: '/supply/skus' }),
}));
const __VLS_115 = __VLS_114({
    index: "/supply/skus",
    route: ({ path: '/supply/skus' }),
}, ...__VLS_functionalComponentArgsRest(__VLS_114));
__VLS_116.slots.default;
var __VLS_116;
const __VLS_117 = {}.ElMenuItem;
/** @type {[typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, ]} */ ;
// @ts-ignore
const __VLS_118 = __VLS_asFunctionalComponent(__VLS_117, new __VLS_117({
    index: "/ecosystem/partners",
    route: ({ path: '/ecosystem/partners' }),
}));
const __VLS_119 = __VLS_118({
    index: "/ecosystem/partners",
    route: ({ path: '/ecosystem/partners' }),
}, ...__VLS_functionalComponentArgsRest(__VLS_118));
__VLS_120.slots.default;
var __VLS_120;
var __VLS_104;
const __VLS_121 = {}.ElMenuItem;
/** @type {[typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, typeof __VLS_components.ElMenuItem, typeof __VLS_components.elMenuItem, ]} */ ;
// @ts-ignore
const __VLS_122 = __VLS_asFunctionalComponent(__VLS_121, new __VLS_121({
    index: "/traces",
    route: ({ path: '/traces' }),
}));
const __VLS_123 = __VLS_122({
    index: "/traces",
    route: ({ path: '/traces' }),
}, ...__VLS_functionalComponentArgsRest(__VLS_122));
__VLS_124.slots.default;
const __VLS_125 = {}.ElIcon;
/** @type {[typeof __VLS_components.ElIcon, typeof __VLS_components.elIcon, typeof __VLS_components.ElIcon, typeof __VLS_components.elIcon, ]} */ ;
// @ts-ignore
const __VLS_126 = __VLS_asFunctionalComponent(__VLS_125, new __VLS_125({}));
const __VLS_127 = __VLS_126({}, ...__VLS_functionalComponentArgsRest(__VLS_126));
__VLS_128.slots.default;
const __VLS_129 = {}.Document;
/** @type {[typeof __VLS_components.Document, ]} */ ;
// @ts-ignore
const __VLS_130 = __VLS_asFunctionalComponent(__VLS_129, new __VLS_129({}));
const __VLS_131 = __VLS_130({}, ...__VLS_functionalComponentArgsRest(__VLS_130));
var __VLS_128;
{
    const { title: __VLS_thisSlot } = __VLS_124.slots;
}
var __VLS_124;
var __VLS_8;
var __VLS_3;
/** @type {__VLS_StyleScopedClasses['sidebar']} */ ;
/** @type {__VLS_StyleScopedClasses['sidebar__brand']} */ ;
/** @type {__VLS_StyleScopedClasses['sidebar__brand-dot']} */ ;
/** @type {__VLS_StyleScopedClasses['sidebar__brand-text']} */ ;
/** @type {__VLS_StyleScopedClasses['sidebar__menu']} */ ;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            Histogram: Histogram,
            User: User,
            TrendCharts: TrendCharts,
            DataAnalysis: DataAnalysis,
            Box: Box,
            Document: Document,
            route: route,
            collapsed: collapsed,
            defaultOpeneds: defaultOpeneds,
        };
    },
});
export default (await import('vue')).defineComponent({
    setup() {
        return {};
    },
});
; /* PartiallyEnd: #4569/main.vue */
//# sourceMappingURL=Sidebar.vue.js.map