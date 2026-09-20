// Maps a body-region's raw exposure score (0-100, or null when unpublished) onto one of
// the map's 4 colour tiers. The real body-regions endpoint has no band/level field — just
// a number — so these thresholds are a frontend display choice, not something the backend
// specifies.
export function physicalDemandColorClass(score: number | null | undefined): string {
  if (score === null || score === undefined) return 'risk-1'
  if (score >= 65) return 'risk-4'
  if (score >= 45) return 'risk-3'
  if (score >= 25) return 'risk-2'
  return 'risk-1'
}
