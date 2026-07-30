export function petProfileValue(value: string | null | undefined): string {
  if (!value || value.trim() === '' || value.toLowerCase() === 'unknown') {
    return '待完善'
  }
  return value
}

export function isPetProfilePending(pet: {
  species: string | null
  breed: string | null
  onboarding_pending: boolean
}): boolean {
  return pet.onboarding_pending || petProfileValue(pet.species) === '待完善' || petProfileValue(pet.breed) === '待完善'
}
