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
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `DATABASE_URL` and `NVIDIA_API_KEY` in `backend/.env`, create/load the
PostgreSQL database as described in the backend README, then run:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Swagger UI: <http://127.0.0.1:8000/docs>

## Frontend

```powershell
cd frontend
npm install
npm run dev
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
.\.venv\Scripts\python.exe -m pytest tests/test_chat.py tests/test_occupation_demand_search.py -q
```

Frontend production build:

```powershell
cd frontend
npm run build
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
