import axios, { type AxiosInstance } from 'axios'
import { ElMessage } from 'element-plus'

export const http: AxiosInstance = axios.create({
  baseURL: '/api/admin',
  timeout: 30000
})

http.interceptors.request.use((cfg) => {
  const token = localStorage.getItem('petops.admin.token')
  if (token) {
    cfg.headers = cfg.headers ?? {}
    cfg.headers.Authorization = `Bearer ${token}`
  }
  return cfg
})

http.interceptors.response.use(
  (r) => r,
  (err) => {
    const status = err.response?.status
    if (status === 401) {
      // token 失效：清掉本地 + 跳登录页
      localStorage.removeItem('petops.admin.token')
      localStorage.removeItem('petops.admin.user')
      if (location.pathname !== '/login' && !location.pathname.startsWith('/bigscreen')) {
        location.href = '/admin/login'
      }
    }
    const msg = err.response?.data?.detail ?? err.message ?? '请求失败'
    ElMessage.error(String(msg))
    return Promise.reject(err)
  }
)
