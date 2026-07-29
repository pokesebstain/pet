<template>
  <el-drawer
    :model-value="modelValue"
    :title="title"
    direction="rtl"
    size="480px"
    @update:model-value="$emit('update:modelValue', $event)"
    @closed="$emit('closed')"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
      <slot :form="form" />
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="onSubmit">
        保存
      </el-button>
    </template>
  </el-drawer>
</template>

<script setup lang="ts" generic="T extends Record<string, unknown>">
import { ref } from 'vue'
import { ElMessage, type FormInstance } from 'element-plus'

interface Props {
  modelValue: boolean
  title: string
  form: T
  rules?: Record<string, unknown>
  submitting?: boolean
}
withDefaults(defineProps<Props>(), { submitting: false })

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'submit', form: T): void
  (e: 'closed'): void
}>()

const formRef = ref<FormInstance>()

function onSubmit() {
  formRef.value?.validate((ok) => {
    if (!ok) {
      ElMessage.warning('请检查表单')
      return
    }
    emit('submit', (formRef.value?.modelValue ?? {}) as T)
  })
}
</script>
