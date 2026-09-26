# Telosia Project

This repository packages the current Telosia backend and frontend into one
development workspace.

## Repository layout

```text
telosia-project/
├── backend/   FastAPI, PostgreSQL, ETL, local FAISS RAG, and NVIDIA NIM chat
└── frontend/  Vue 3, TypeScript, Vite, and the Telosia chatbot interface
```

The backend and frontend were copied as a source snapshot. Their original
nested Git histories, local environments, dependency folders, build outputs,
raw source datasets, and secrets are intentionally not included.

## Backend

See [`backend/README.md`](backend/README.md) for the database setup, available
API endpoints, data boundaries, RAG artifacts, and chatbot architecture.

Quick start on Windows PowerShell:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
# New checkouts only: never overwrite an existing .env.
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

Set `DATABASE_URL` and `NVIDIA_API_KEY` in `backend/.env`, create/load the
PostgreSQL database as described in the backend README, then run:

```powershell
.\start_backend.cmd
```

Swagger UI: <http://127.0.0.1:8000/docs>

The Windows launcher always uses `backend/.venv` and `backend/.env`, even if a
different virtual environment is active in your terminal. Local `.env` values
override stale shell settings. Restart the backend after editing `.env`;
`.env.example` is documentation only and is not loaded at runtime. Do not use
a sibling project's Python or `.env`. No PowerShell activation script is needed.

## Frontend

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

For local development, create `frontend/.env.local` containing:

```env
VITE_API_BASE_URL=/api/v1
```

The Vite development proxy forwards `/api` requests to
`http://127.0.0.1:8000`.

## Verification

Backend chatbot tests:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_chat.py tests/test_chat_data.py -q
```

Frontend production build:

```powershell
cd frontend
npm.cmd run build
```

## Security and data handling

- Never commit `.env`, `.env.local`, API keys, database passwords, or service
  credentials.
- The NVIDIA key belongs only in the backend environment and must never be
  exposed through Vue/Vite environment variables.
- Raw and locally reviewed data files remain outside this packaged repository
  unless their licensing, privacy, and team approval have been confirmed.
- BOHD exposure values are work-demand measures, not observed body-part injury
  claims, diagnoses, or personal medical-risk predictions.

## Attribution

Telosia is a collaborative FIT5120 project. Dataset-specific publishers,
licences, coverage periods, and attribution text are retained in the backend
source metadata and documented in `backend/README.md`.
