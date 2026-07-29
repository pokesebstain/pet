import { http } from '@/api/client'

export interface PageResp<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export async function listPage<T>(
  path: string,
  params: Record<string, unknown> = {}
): Promise<PageResp<T>> {
  const { data } = await http.get<PageResp<T>>(path, { params })
  return data
}

export async function getOne<T>(path: string): Promise<T> {
  const { data } = await http.get<T>(path)
  return data
}

export async function createOne<T>(path: string, payload: unknown): Promise<T> {
  const { data } = await http.post<T>(path, payload)
  return data
}

export async function updateOne<T>(path: string, payload: unknown): Promise<T> {
  const { data } = await http.put<T>(path, payload)
  return data
}

export async function deleteOne(path: string): Promise<void> {
  await http.delete(path)
}
