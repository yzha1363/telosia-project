# Telosia — Frontend

Shows what a job asks of your body, and where people who did that job actually moved into next.
Free, no account, built from published Australian workforce and safety data.

Vue 3 + TypeScript + Vite. Talks to a real backend over `fetch` — the base URL lives in
`src/api/config.ts` (currently `https://telosia.fastapicloud.dev/api/v1`). See
[API_REQUIREMENTS.md](API_REQUIREMENTS.md) for the endpoint contract.

## Getting started

Requires Node `^22.18.0` or `>=24.12.0`.

```sh
npm install
npm run dev
```

Opens at `http://localhost:5173`.

## Scripts

| command | what it does |
|---|---|
| `npm run dev` | start the dev server |
| `npm run build` | type-check, then build for production |
| `npm run preview` | preview the production build locally |
| `npm run type-check` | run `vue-tsc` without building |
| `npm run lint` | run oxlint + eslint, auto-fixing |
| `npm run format` | run prettier on `src/` |

## Project structure

```
src/
├── views/       one file per route/page
├── components/  shared UI pieces (body map, header/footer, dialogs, cards)
├── data/        shared TypeScript types (src/data/types.ts)
├── store/       small reactive singletons for shared app state (no Pinia)
├── router/      route definitions and navigation guards
├── api/         backend base URL config
├── utils/       small pure helper functions
├── directives/  custom Vue directives (scroll reveal, count-up animation)
└── assets/      global stylesheet and images
```

## Pages

| path | page |
|---|---|
| `/` | Home |
| `/check-my-job` | Search and confirm an occupation |
| `/risk` | Physical demand profile / body map for the confirmed occupation |
| `/destinations` | Where people in that job moved to next |
| `/how-it-works` | How it works |
| `/hurt-at-work` | Hurt at work |
| `/about-us` | About us |

`/risk` and `/destinations` redirect back to `/check-my-job` if no occupation has been confirmed
yet (`src/router/index.ts`).
