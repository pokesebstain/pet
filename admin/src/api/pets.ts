import { http } from './client'
import { listPage, getOne, createOne, updateOne, deleteOne } from '@/utils/http'

export interface Pet {
  pet_id: string
  owner_id: string
  name: string | null
  species: string
  breed: string
  birth_date: string | null
  weight_kg: number | null
  life_stage: string | null
  onboarding_pending: boolean
}

export const petsApi = {
  list: (page: number, pageSize: number, search?: string) =>
    listPage<Pet>('/pets', { page, page_size: pageSize, search }),
  get: (id: string) => getOne<Pet>(`/pets/${id}`),
  create: (payload: Partial<Pet>) => createOne<Pet>('/pets', payload),
  update: (id: string, payload: Partial<Pet>) => updateOne<Pet>(`/pets/${id}`, payload),
  remove: (id: string) => deleteOne(`/pets/${id}`)
}
