import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import AppLayout from '@/components/layout/AppLayout.vue'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: AppLayout,
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

export default createRouter({
  history: createWebHistory('/admin/'),
  routes
})
