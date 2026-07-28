import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', component: () => import('@/views/DashboardView.vue') },
  { path: '/customers', component: () => import('@/views/customers/ListView.vue') },
  { path: '/customers/:id', component: () => import('@/views/customers/DetailView.vue') }
]

export default createRouter({
  history: createWebHistory('/admin/'),
  routes
})