import axios, { type AxiosInstance } from 'axios'
import { ElMessage } from 'element-plus'

export const http: AxiosInstance = axios.create({
  baseURL: '/api/admin',
  timeout: 30000
})

http.interceptors.response.use(
  (r) => r,
  (err) => {
    const msg = err.response?.data?.detail ?? err.message ?? '请求失败'
    ElMessage.error(String(msg))
    return Promise.reject(err)
  }
)
