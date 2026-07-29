<template>
  <div class="login">
    <el-card class="login__card" shadow="always">
      <h2 class="login__title">PetOps Admin</h2>
      <p class="login__hint">店主后台 · 请用 .env 里配置的账号登录</p>
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        @keyup.enter="onSubmit"
      >
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" placeholder="admin" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password />
        </el-form-item>
        <el-button
          type="primary"
          :loading="submitting"
          class="login__submit"
          @click="onSubmit"
        >
          登录
        </el-button>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance } from 'element-plus'
import { authApi } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()
const formRef = ref<FormInstance>()
const submitting = ref(false)
const form = reactive({ username: 'admin', password: '' })

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

async function onSubmit() {
  if (!formRef.value) return
  await formRef.value.validate(async (ok) => {
    if (!ok) return
    submitting.value = true
    try {
      const r = await authApi.login(form.username, form.password)
      auth.setAuth(r.token, r.username)
      ElMessage.success(`欢迎，${r.username}`)
      router.push('/dashboard')
    } catch (e) {
      /* interceptor 已 toast */
    } finally {
      submitting.value = false
    }
  })
}
</script>

<style scoped>
.login {
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  display: flex;
  align-items: center;
  justify-content: center;
}
.login__card {
  width: 380px;
  padding: 24px 8px;
}
.login__title {
  text-align: center;
  margin: 0 0 8px;
  font-size: 24px;
  font-weight: 600;
  color: #303133;
}
.login__hint {
  text-align: center;
  color: #909399;
  font-size: 13px;
  margin: 0 0 24px;
}
.login__submit {
  width: 100%;
  margin-top: 8px;
}
</style>
