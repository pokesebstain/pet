import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import AppLayout from '@/components/layout/AppLayout.vue'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  { path: '/login', component: () => import('@/views/LoginView.vue'), meta: { public: true, title: '登录' } },
  { path: '/bigscreen', component: () => import('@/views/bigscreen/BigscreenView.vue'), meta: { public: true, title: '经营大屏' } },
  {
    path: '/',
    component: AppLayout,
    meta: { requiresAuth: true },
    children: [
      { path: '', redirect: '/dashboard' },
      { path: 'dashboard', component: () => import('@/views/DashboardView.vue'), meta: { title: '仪表盘' } },
      { path: 'customers', component: () => import('@/views/customers/ListView.vue'), meta: { title: '客户管理' } },
      { path: 'customers/:id', component: () => import('@/views/customers/DetailView.vue'), meta: { title: '客户详情' } },
      { path: 'pets', component: () => import('@/views/pets/ListView.vue'), meta: { title: '宠物档案' } },
      { path: 'pets/:id', component: () => import('@/views/pets/DetailView.vue'), meta: { title: '宠物详情' } },
      { path: 'appointments', component: () => import('@/views/appointments/ListView.vue'), meta: { title: '预约管理' } },
      { path: 'business-hours', component: () => import('@/views/business-hours/View.vue'), meta: { title: '营业时间' } },
      { path: 'resources', component: () => import('@/views/resources/View.vue'), meta: { title: '美容资源' } },
      { path: 'health/metrics', component: () => import('@/views/health/MetricsView.vue'), meta: { title: '健康指标' } },
      { path: 'health/alerts', component: () => import('@/views/health/AlertsView.vue'), meta: { title: '健康告警' } },
      { path: 'operations/ltv', component: () => import('@/views/operations/LtvView.vue'), meta: { title: 'LTV 分群' } },
      { path: 'operations/churn', component: () => import('@/views/operations/ChurnView.vue'), meta: { title: '流失风险' } },
      { path: 'supply/skus', component: () => import('@/views/supply/SkusView.vue'), meta: { title: 'SKU 管理' } },
      { path: 'marketing/contents', component: () => import('@/views/marketing/ContentsView.vue'), meta: { title: '营销内容' } },
      { path: 'subscriptions', component: () => import('@/views/subscriptions/ListView.vue'), meta: { title: '订阅管理' } },
      { path: 'ecosystem/partners', component: () => import('@/views/ecosystem/PartnersView.vue'), meta: { title: '合作医院' } },
      { path: 'traces', component: () => import('@/views/traces/ListView.vue'), meta: { title: '对话追溯' } },
      { path: 'traces/:thread_id', component: () => import('@/views/traces/DetailView.vue'), meta: { title: '对话详情' } }
    ]
  }
]

const router = createRouter({
  history: createWebHistory('/admin/'),
  routes
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.public) return true
  if (to.meta.requiresAuth && !auth.token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  // 已登录访问 /login → 跳 dashboard
  if (to.path === '/login' && auth.token) {
    return { path: '/dashboard' }
  }
  return true
})

export default router
