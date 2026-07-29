import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import AppLayout from '@/components/layout/AppLayout.vue'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  { path: '/login', component: () => import('@/views/LoginView.vue'), meta: { public: true } },
  { path: '/bigscreen', component: () => import('@/views/bigscreen/BigscreenView.vue'), meta: { public: true } },
  {
    path: '/',
    component: AppLayout,
    meta: { requiresAuth: true },
    children: [
      { path: '', redirect: '/dashboard' },
      { path: 'dashboard', component: () => import('@/views/DashboardView.vue') },
      { path: 'customers', component: () => import('@/views/customers/ListView.vue') },
      { path: 'customers/:id', component: () => import('@/views/customers/DetailView.vue') },
      { path: 'pets', component: () => import('@/views/pets/ListView.vue') },
      { path: 'pets/:id', component: () => import('@/views/pets/DetailView.vue') },
      { path: 'appointments', component: () => import('@/views/appointments/ListView.vue') },
      { path: 'business-hours', component: () => import('@/views/business-hours/View.vue') },
      { path: 'resources', component: () => import('@/views/resources/View.vue') },
      { path: 'health/metrics', component: () => import('@/views/health/MetricsView.vue') },
      { path: 'health/alerts', component: () => import('@/views/health/AlertsView.vue') },
      { path: 'operations/ltv', component: () => import('@/views/operations/LtvView.vue') },
      { path: 'operations/churn', component: () => import('@/views/operations/ChurnView.vue') },
      { path: 'supply/skus', component: () => import('@/views/supply/SkusView.vue') },
      { path: 'marketing/contents', component: () => import('@/views/marketing/ContentsView.vue') },
      { path: 'subscriptions', component: () => import('@/views/subscriptions/ListView.vue') },
      { path: 'ecosystem/partners', component: () => import('@/views/ecosystem/PartnersView.vue') },
      { path: 'traces', component: () => import('@/views/traces/ListView.vue') },
      { path: 'traces/:thread_id', component: () => import('@/views/traces/DetailView.vue') }
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
