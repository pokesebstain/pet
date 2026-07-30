import { describe, expect, it } from 'vitest'
import { isPetProfilePending, petProfileValue } from './pet-profile'

// **Validates: Requirements 26.5**
describe('pet profile display', () => {
  it('renders null, blank, and legacy unknown profile values as 待完善', () => {
    expect(petProfileValue(null)).toBe('待完善')
    expect(petProfileValue('  ')).toBe('待完善')
    expect(petProfileValue('unknown')).toBe('待完善')
  })

  it('marks a pet as pending when either core profile field is missing', () => {
    expect(isPetProfilePending({ species: 'dog', breed: null, onboarding_pending: false })).toBe(true)
    expect(isPetProfilePending({ species: 'dog', breed: '柯基', onboarding_pending: false })).toBe(false)
  })
})
