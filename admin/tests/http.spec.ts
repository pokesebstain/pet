import { describe, expect, it, vi, beforeEach } from 'vitest'

// 用 vi.mock 直接拦截整个 client 模块
const mockGet = vi.fn()
const mockPost = vi.fn()
const mockPut = vi.fn()
const mockDelete = vi.fn()

vi.mock('@/api/client', () => ({
  http: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
    put: (...args: unknown[]) => mockPut(...args),
    delete: (...args: unknown[]) => mockDelete(...args)
  }
}))

// import 必须在 vi.mock 之后
import { listPage, getOne, createOne, updateOne, deleteOne } from '@/utils/http'

beforeEach(() => {
  vi.clearAllMocks()
})

describe('http utils', () => {
  it('listPage unwraps axios data into PageResp', async () => {
    mockGet.mockResolvedValue({
      data: { items: [{ id: 1 }], total: 1, page: 1, page_size: 20 }
    })
    const r = await listPage('/foo')
    expect(r.total).toBe(1)
    expect(r.items[0].id).toBe(1)
    expect(mockGet).toHaveBeenCalledWith('/foo', { params: {} })
  })

  it('listPage forwards params', async () => {
    mockGet.mockResolvedValue({
      data: { items: [], total: 0, page: 2, page_size: 50 }
    })
    await listPage('/foo', { page: 2, page_size: 50 })
    expect(mockGet).toHaveBeenCalledWith('/foo', { params: { page: 2, page_size: 50 } })
  })

  it('getOne returns data', async () => {
    mockGet.mockResolvedValue({ data: { id: '1' } })
    const r = await getOne('/foo/1')
    expect(r.id).toBe('1')
    expect(mockGet).toHaveBeenCalledWith('/foo/1')
  })

  it('createOne calls POST', async () => {
    mockPost.mockResolvedValue({ data: { id: 'new' } })
    const r = await createOne('/foo', { name: 'X' })
    expect(r.id).toBe('new')
    expect(mockPost).toHaveBeenCalledWith('/foo', { name: 'X' })
  })

  it('updateOne calls PUT', async () => {
    mockPut.mockResolvedValue({ data: { id: '1' } })
    const r = await updateOne('/foo/1', { name: 'Y' })
    expect(r.id).toBe('1')
    expect(mockPut).toHaveBeenCalledWith('/foo/1', { name: 'Y' })
  })

  it('deleteOne calls DELETE', async () => {
    mockDelete.mockResolvedValue({})
    await deleteOne('/foo/1')
    expect(mockDelete).toHaveBeenCalledWith('/foo/1')
  })
})
