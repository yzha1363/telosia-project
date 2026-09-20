// Single source of truth for the backend base URL. Local development can set
// VITE_API_BASE_URL in .env.local; production falls back to the deployed API.
export const API_BASE = (
  import.meta.env.VITE_API_BASE_URL ?? 'https://telosia.fastapicloud.dev/api/v1'
).replace(/\/$/, '')
