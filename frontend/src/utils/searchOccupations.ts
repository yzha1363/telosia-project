import type { Occupation } from '../data/types'

export interface OccupationMatch extends Occupation {
  matchedAlias?: string
}

export function normalize(value: string): string {
  return value.trim().toLowerCase()
}
