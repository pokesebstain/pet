import { ref } from 'vue';
import { ElMessage } from 'element-plus';
export default ((__VLS_props, __VLS_ctx, __VLS_expose, __VLS_setup = (async () => {
    const props = withDefaults(defineProps(), { submitting: false });
    const emit = defineEmits();
    const formRef = ref();
    function onSubmit() {
        formRef.value?.validate((ok) => {
            if (!ok) {
                ElMessage.warning('请检查表单');
                return;
            }
            emit('submit', props.form);
        });
    }
    debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
    const __VLS_withDefaultsArg = (function (t) { return t; })({ submitting: false });
    const __VLS_fnComponent = (await import('vue')).defineComponent({
        __typeEmits: {},
    });
    const __VLS_ctx = {};
    let __VLS_components;
    let __VLS_directives;
    const __VLS_0 = {}.ElDrawer;
    /** @type {[typeof __VLS_components.ElDrawer, typeof __VLS_components.elDrawer, typeof __VLS_components.ElDrawer, typeof __VLS_components.elDrawer, ]} */ ;
    // @ts-ignore
    const __VLS_1 = __VLS_asFunctionalComponent(__VLS_0, new __VLS_0({
        ...{ 'onUpdate:modelValue': {} },
        ...{ 'onClosed': {} },
        modelValue: (__VLS_ctx.modelValue),
        title: (__VLS_ctx.title),
        direction: "rtl",
        size: "480px",
    }));
    const __VLS_2 = __VLS_1({
        ...{ 'onUpdate:modelValue': {} },
        ...{ 'onClosed': {} },
        modelValue: (__VLS_ctx.modelValue),
        title: (__VLS_ctx.title),
        direction: "rtl",
        size: "480px",
    }, ...__VLS_functionalComponentArgsRest(__VLS_1));
    let __VLS_4;
    let __VLS_5;
    let __VLS_6;
    const __VLS_7 = {
        'onUpdate:modelValue': (...[$event]) => {
            __VLS_ctx.$emit('update:modelValue', $event);
        }
    };
    const __VLS_8 = {
        onClosed: (...[$event]) => {
            __VLS_ctx.$emit('closed');
        }
    };
    var __VLS_9 = {};
    __VLS_3.slots.default;
    const __VLS_10 = {}.ElForm;
    /** @type {[typeof __VLS_components.ElForm, typeof __VLS_components.elForm, typeof __VLS_components.ElForm, typeof __VLS_components.elForm, ]} */ ;
    // @ts-ignore
    const __VLS_11 = __VLS_asFunctionalComponent(__VLS_10, new __VLS_10({
        ref: "formRef",
        model: (__VLS_ctx.form),
        rules: (__VLS_ctx.rules),
        labelWidth: "100px",
    }));
    const __VLS_12 = __VLS_11({
        ref: "formRef",
        model: (__VLS_ctx.form),
        rules: (__VLS_ctx.rules),
        labelWidth: "100px",
    }, ...__VLS_functionalComponentArgsRest(__VLS_11));
    /** @type {typeof __VLS_ctx.formRef} */ ;
    var __VLS_14 = {};
    __VLS_13.slots.default;
    var __VLS_16 = {
        form: (__VLS_ctx.form),
    };
    var __VLS_13;
    {
        const { footer: __VLS_thisSlot } = __VLS_3.slots;
        const __VLS_18 = {}.ElButton;
        /** @type {[typeof __VLS_components.ElButton, typeof __VLS_components.elButton, typeof __VLS_components.ElButton, typeof __VLS_components.elButton, ]} */ ;
        // @ts-ignore
        const __VLS_19 = __VLS_asFunctionalComponent(__VLS_18, new __VLS_18({
            ...{ 'onClick': {} },
        }));
        const __VLS_20 = __VLS_19({
            ...{ 'onClick': {} },
        }, ...__VLS_functionalComponentArgsRest(__VLS_19));
        let __VLS_22;
        let __VLS_23;
        let __VLS_24;
        const __VLS_25 = {
            onClick: (...[$event]) => {
                __VLS_ctx.$emit('update:modelValue', false);
            }
        };
        __VLS_21.slots.default;
        var __VLS_21;
        const __VLS_26 = {}.ElButton;
        /** @type {[typeof __VLS_components.ElButton, typeof __VLS_components.elButton, typeof __VLS_components.ElButton, typeof __VLS_components.elButton, ]} */ ;
        // @ts-ignore
        const __VLS_27 = __VLS_asFunctionalComponent(__VLS_26, new __VLS_26({
            ...{ 'onClick': {} },
            type: "primary",
            loading: (__VLS_ctx.submitting),
        }));
        const __VLS_28 = __VLS_27({
            ...{ 'onClick': {} },
            type: "primary",
            loading: (__VLS_ctx.submitting),
        }, ...__VLS_functionalComponentArgsRest(__VLS_27));
        let __VLS_30;
        let __VLS_31;
        let __VLS_32;
        const __VLS_33 = {
            onClick: (__VLS_ctx.onSubmit)
        };
        __VLS_29.slots.default;
        var __VLS_29;
    }
    var __VLS_3;
    // @ts-ignore
    var __VLS_15 = __VLS_14, __VLS_17 = __VLS_16;
    var __VLS_dollars;
    const __VLS_self = (await import('vue')).defineComponent({
        setup() {
            return {
                formRef: formRef,
                onSubmit: onSubmit,
            };
        },
        __typeEmits: {},
        __typeProps: {},
        props: {},
    });
    return {};
})()) => ({})); /* PartiallyEnd: #4569/main.vue */
//# sourceMappingURL=FormDrawer.vue.js.map