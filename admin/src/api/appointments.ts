import { http } from './client'
import { listPage, getOne, createOne, updateOne, deleteOne } from '@/utils/http'

export interface Appointment {
  appointment_id: string
  customer_id: string
  pet_id: string
  service_type: string
  start_at: string
  end_at: string
  resource_id: string | null
  status: string
  source: string
}

export const appointmentsApi = {
  list: (page: number, pageSize: number, filters: Record<string, unknown> = {}) =>
    listPage<Appointment>('/appointments', { page, page_size: pageSize, ...filters }),
  get: (id: string) => getOne<Appointment>(`/appointments/${id}`),
  create: (payload: Partial<Appointment>) => createOne<Appointment>('/appointments', payload),
  update: (id: string, payload: Partial<Appointment>) => updateOne<Appointment>(`/appointments/${id}`, payload),
  cancel: (id: string) => deleteOne(`/appointments/${id}`)
}
