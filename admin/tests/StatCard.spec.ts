import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import StatCard from '@/components/common/StatCard.vue'

describe('StatCard', () => {
  it('renders label and value', () => {
    const w = mount(StatCard, { props: { label: '今日预约', value: 42 } })
    expect(w.text()).toContain('今日预约')
    expect(w.text()).toContain('42')
  })

  it('shows up trend for positive number', () => {
    const w = mount(StatCard, { props: { label: 'X', value: 1, trend: 5 } })
    expect(w.text()).toContain('↑')
  })

  it('shows down trend for negative number', () => {
    const w = mount(StatCard, { props: { label: 'X', value: 1, trend: -3 } })
    expect(w.text()).toContain('↓')
  })

  it('hides trend when undefined', () => {
    const w = mount(StatCard, { props: { label: 'X', value: 1 } })
    expect(w.find('.stat-card__trend').exists()).toBe(false)
  })
})
