# Telosia — Frontend API Requirements (Iteration 2)

This document describes the API contract the frontend still needs from the backend for
iteration 2. Iteration 1's contract — the endpoints already built, merged, and connected
(search, occupation lookup, body-regions, destinations, sources) — is preserved as-is on the
`frontend-iteration1` branch's copy of this file and isn't repeated here. The current frontend
still calls all of those endpoints; this document only tracks what's new or still missing.

## 1. Conventions

- All responses are JSON, `camelCase` field names.
- No authentication — the app has no login (AC requirement).
- Base path: `/api/v1` (examples below omit it).
- Every numeric figure the UI displays must be traceable to a `sourceId`. A statistic with no matching source record must not be sent.

## 2. Needed — destinations page filters (2026-09-15)

**Extend `GET /occupations/{occupationId}` with:**

| Field | Description | Example |
|---|---|---|
| `medianWeeklyPay` | Median weekly pay for this occupation | `1450` |
| `partTimePercentage` | Share of workers in this occupation who are part-time | `32.5` |
| `womenPercentage` | Share of workers in this occupation who are women | `86.0` |
| `automationExposure` | Automation exposure score, out of 100 | `71` |
| `entryRequirement` | Plain-language entry requirement text | `Certificate III in Individual Support` |
| `genderPayGap` | Gender pay gap, percent | `5.9` |
| `injuryFrequencySignal` | How this occupation's injury frequency compares to occupations generally. One of `higher_than_typical`, `about_typical`, `lower_than_typical`, or `null` if not published for this occupation | `higher_than_typical` |

**Extend `GET /occupations/{occupationId}/destinations` with sorting and filtering** — all of it
server-side, so the frontend just requests the page it wants and renders what comes back.

Query params:

| Param | Type | Description | Example |
|---|---|---|---|
| `sort` | string | One of `most_common`, `kindest_overall`, `best_relief`, `highest_pay`, `most_part_time`, `most_women`, `least_automation`, `a_to_z` | `best_relief` |
| `compareRegion` | string | One of `Lower back`, `Shoulders and upper arms`, `Hands and wrists`, `Knees`, `Legs and feet`, `Whole body and fall risk` — used for `best_relief` sort. Omit for whole-body | `Knees` |
| `showHarderMoves` | boolean | Include destinations with equal or harder overall body load than the current occupation. Default `true` | `false` |
| `states` | string | Comma-separated state codes — see valid values below | `VIC,NSW` |
| `sa4Regions` | string | Comma-separated Victorian SA4 codes — see valid values below | `mel-inner` |

New fields per destination row in the response:

| Field | Description | Example |
|---|---|---|
| `bodyLoadBand` | One of `down` / `up` / `same` — this destination's overall body load compared to the current occupation. `null` if either occupation has no body-regions data to compare | `down` |
| `regionSharePercentage` | Present only when `states`/`sa4Regions` are supplied — this occupation's workforce share in the requested region(s). Cites the same `source_id` already on this row, not a separate one | `25.9` |

Valid `states` values — real ABS states:

```
VIC, NSW, QLD, WA, SA, TAS, ACT, NT
```

Valid `sa4Regions` values — real Victorian SA4s:

```
mel-inner, mel-inner-east, mel-inner-south, mel-north-east, mel-north-west, mel-outer-east,
mel-south-east, mel-west, mornington, ballarat, bendigo, geelong, hume, latrobe, nw-vic,
shepparton, warrnambool
```

If `states`/`sa4Regions` filter out every destination, return an empty `destinations` array —
don't trigger `isFallback`/`group`, which means something different (no transition data exists
for this occupation at all, unrelated to what the user filtered by).

Not in scope here: the destination detail panel's own body-region comparison ("What it costs
your body") stays a frontend computation from `body-regions` — only the destinations *list*
sort/filter moves server-side.

