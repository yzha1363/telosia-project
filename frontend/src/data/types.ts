export interface Occupation {
  id: string
  title: string
  aliases: string[]
}

// Matches GET /occupations/{id}/body-regions exactly (real, merged endpoint — iteration 1,
// preserved on frontend-iteration1). Only 6 regions exist, one of which ("Whole body and
// fall risk") isn't an anatomical location at all — there's no level/band field, just a
// raw score, and no per-region source (one page-level methodology covers all of them).
export interface BodyRegionContributor {
  variable: string
  score: number
}

export interface BodyRegion {
  region: string
  score: number | null
  contributors: BodyRegionContributor[]
  message: string | null
}

// The 6 region names, exact strings as returned by the endpoint — used to key the body
// map's clickable shapes to a region.
export type BodyRegionName =
  | 'Lower back'
  | 'Shoulders and upper arms'
  | 'Hands and wrists'
  | 'Knees'
  | 'Legs and feet'
  | 'Whole body and fall risk'

// sourceId is a real field the endpoint returns per row (same value across every row for
// one occupation — iteration 1, preserved on frontend-iteration1). tasks is optional because
// the destinations endpoint itself doesn't return it — it's merged in separately from the
// occupation entity.
export interface Destination {
  id: number
  title: string
  share: number
  tag: string
  sourceId: number
  tasks?: string[]
  description?: string | null
  bodyLoadBand?: 'up' | 'down' | 'same' | null
  regionSharePercentage?: number | null
  tier?: 'Lower than typical' | 'About typical' | 'Higher than typical' | null
}
