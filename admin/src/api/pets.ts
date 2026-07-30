import { http } from './client'
import { listPage, getOne, createOne, updateOne, deleteOne } from '@/utils/http'

export interface Pet {
  pet_id: string
  owner_id: string
  name: string | null
  species: string | null
  breed: string | null
  birth_date: string | null
  weight_kg: number | null
  life_stage: string | null
  onboarding_pending: boolean
}

export interface PetInput {
  owner_id: string
  name?: string | null
  species?: string | null
  breed?: string | null
  birth_date?: string | null
  weight_kg?: number | null
  life_stage?: string | null
}

export const petsApi = {
  list: (page: number, pageSize: number, search?: string, onboardingPending?: boolean, ownerId?: string) =>
    listPage<Pet>('/pets', {
      page,
      page_size: pageSize,
      search,
      onboarding_pending: onboardingPending,
      owner_id: ownerId
    }),
  get: (id: string) => getOne<Pet>(`/pets/${id}`),
  create: (payload: PetInput) => createOne<Pet>('/pets', payload),
  update: (id: string, payload: PetInput) => updateOne<Pet>(`/pets/${id}`, payload),
  remove: (id: string) => deleteOne(`/pets/${id}`)
}
