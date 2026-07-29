import { ref, watch } from 'vue';
export default ((__VLS_props, __VLS_ctx, __VLS_expose, __VLS_setup = (async () => {
    const props = withDefaults(defineProps(), {
        loading: false,
        initialPage: 1,
        initialPageSize: 20
    });
    const __VLS_emit = defineEmits();
    const page = ref(props.initialPage);
    const pageSize = ref(props.initialPageSize);
    watch(() => props.initialPage, (v) => { page.value = v; });
    debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
    const __VLS_withDefaultsArg = (function (t) { return t; })({
        loading: false,
        initialPage: 1,
        initialPageSize: 20
    });
    const __VLS_fnComponent = (await import('vue')).defineComponent({
        __typeEmits: {},
    });
    const __VLS_ctx = {};
    let __VLS_components;
    let __VLS_directives;
    // CSS variable injection 
    // CSS variable injection end 
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "data-table" },
    });
    if (__VLS_ctx.$slots.toolbar) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "data-table__toolbar" },
        });
        var __VLS_0 = {};
    }
    const __VLS_2 = {}.ElTable;
    /** @type {[typeof __VLS_components.ElTable, typeof __VLS_components.elTable, typeof __VLS_components.ElTable, typeof __VLS_components.elTable, ]} */ ;
    // @ts-ignore
    const __VLS_3 = __VLS_asFunctionalComponent(__VLS_2, new __VLS_2({
        data: (__VLS_ctx.items),
        stripe: true,
        border: true,
    }));
    const __VLS_4 = __VLS_3({
        data: (__VLS_ctx.items),
        stripe: true,
        border: true,
    }, ...__VLS_functionalComponentArgsRest(__VLS_3));
    __VLS_asFunctionalDirective(__VLS_directives.vLoading)(null, { ...__VLS_directiveBindingRestFields, value: (__VLS_ctx.loading) }, null, null);
    __VLS_5.slots.default;
    var __VLS_6 = {};
    var __VLS_5;
    const __VLS_8 = {}.ElPagination;
    /** @type {[typeof __VLS_components.ElPagination, typeof __VLS_components.elPagination, ]} */ ;
    // @ts-ignore
    const __VLS_9 = __VLS_asFunctionalComponent(__VLS_8, new __VLS_8({
        ...{ 'onCurrentChange': {} },
        ...{ 'onSizeChange': {} },
        currentPage: (__VLS_ctx.page),
        pageSize: (__VLS_ctx.pageSize),
        total: (__VLS_ctx.total),
        pageSizes: ([10, 20, 50, 100]),
        layout: "total, sizes, prev, pager, next, jumper",
    }));
    const __VLS_10 = __VLS_9({
        ...{ 'onCurrentChange': {} },
        ...{ 'onSizeChange': {} },
        currentPage: (__VLS_ctx.page),
        pageSize: (__VLS_ctx.pageSize),
        total: (__VLS_ctx.total),
        pageSizes: ([10, 20, 50, 100]),
        layout: "total, sizes, prev, pager, next, jumper",
    }, ...__VLS_functionalComponentArgsRest(__VLS_9));
    let __VLS_12;
    let __VLS_13;
    let __VLS_14;
    const __VLS_15 = {
        onCurrentChange: (...[$event]) => {
            __VLS_ctx.$emit('page-change', __VLS_ctx.page);
        }
    };
    const __VLS_16 = {
        onSizeChange: (...[$event]) => {
            __VLS_ctx.$emit('size-change', __VLS_ctx.pageSize);
        }
    };
    var __VLS_11;
    /** @type {__VLS_StyleScopedClasses['data-table']} */ ;
    /** @type {__VLS_StyleScopedClasses['data-table__toolbar']} */ ;
    // @ts-ignore
    var __VLS_1 = __VLS_0, __VLS_7 = __VLS_6;
    var __VLS_dollars;
    const __VLS_self = (await import('vue')).defineComponent({
        setup() {
            return {
                page: page,
                pageSize: pageSize,
            };
        },
        __typeEmits: {},
        __typeProps: {},
        props: {},
    });
    return {};
})()) => ({})); /* PartiallyEnd: #4569/main.vue */
//# sourceMappingURL=DataTable.vue.js.map