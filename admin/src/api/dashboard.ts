import { http } from './client'

export interface OverviewStats {
  today_appointments: number
  today_new_customers: number
  pending_alerts: number
  low_stock_skus: number
  recent_revenue: number
}

export interface DailyTrendPoint {
  date: string
  appointments: number
  new_customers: number
  health_alerts: number
}

export interface Todo {
  key: string
  label: string
  count: number
  link: string
}

export const dashboardApi = {
  overview: () => http.get<OverviewStats>('/stats/overview').then((r) => r.data),
  trends: (days = 7) =>
    http.get<{ points: DailyTrendPoint[] }>('/stats/trends', { params: { days } }).then((r) => r.data.points),
  todos: () => http.get<Todo[]>('/stats/todos').then((r) => r.data)
}
