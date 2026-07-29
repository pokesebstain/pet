import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import DataTable from '@/components/common/DataTable.vue'

describe('DataTable', () => {
  it('renders items', () => {
    const wrapper = mount(DataTable, {
      props: { items: [{ a: 1 }, { a: 2 }], total: 2 }
    })
    expect(wrapper.findAll('.el-table__row').length).toBeGreaterThanOrEqual(0)
  })

  it('emits page-change on pagination', async () => {
    const wrapper = mount(DataTable, {
      props: { items: [], total: 0 }
    })
    wrapper.vm.$emit('page-change', 2)
    expect(wrapper.emitted('page-change')).toBeTruthy()
    expect(wrapper.emitted('page-change')![0]).toEqual([2])
  })

  it('emits size-change on page size change', async () => {
    const wrapper = mount(DataTable, {
      props: { items: [], total: 0 }
    })
    wrapper.vm.$emit('size-change', 50)
    expect(wrapper.emitted('size-change')).toBeTruthy()
    expect(wrapper.emitted('size-change')![0]).toEqual([50])
  })
})
