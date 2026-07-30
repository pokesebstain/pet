import { http } from './client'
import { listPage, getOne, createOne, updateOne, deleteOne } from '@/utils/http'

export interface Customer {
  customer_id: string
  name: string
  phone: string | null
  registered_at: string
  ltv: number | null
  churn_score: number | null
  segment: string | null
  onboarding_pending: boolean
  pet_count: number
}

export const customersApi = {
  list: (page: number, pageSize: number, search?: string, onboardingPending?: boolean) =>
    listPage<Customer>('/customers', {
      page,
      page_size: pageSize,
      search,
      onboarding_pending: onboardingPending
    }),
  get: (id: string) => getOne<Customer>(`/customers/${id}`),
  create: (payload: { name: string; phone?: string }) =>
    createOne<Customer>('/customers', payload),
  update: (id: string, payload: { name: string; phone?: string }) =>
    updateOne<Customer>(`/customers/${id}`, payload),
  remove: (id: string) => deleteOne(`/customers/${id}`)
}
