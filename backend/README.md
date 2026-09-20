# Telosia Backend

Telosia tells someone what their job is doing to their body, and where people in that job actually went next — built from real Australian workforce and injury data, no account required.

FastAPI + PostgreSQL + SQLAlchemy. Live at **https://telosia.fastapicloud.dev**.

---

## Tech stack

| | |
|---|---|
| API | FastAPI, served via the `fastapi` CLI |
| Database | PostgreSQL (schema-first — see `database/schema.sql`, no ORM/Alembic) |
| DB access | SQLAlchemy engine/session + parameterised SQL |
| ETL | Pandas, OpenPyXL/xlrd, standalone scripts in `etl/` |
| Chat model | NVIDIA NIM through its OpenAI-compatible Chat Completions API |
| Local RAG | Sentence Transformers (`all-MiniLM-L6-v2`) + FAISS cosine similarity |
| Chat orchestration | Deterministic scope/intent routing, PostgreSQL context building, and bounded generation |
| Deployment | FastAPI Cloud (API) + Supabase (Postgres) |

Full pinned dependency list: `requirements.txt`.

## Project structure

```
telosia/
├── app/
│   ├── main.py              FastAPI app, CORS, root + health endpoints
│   ├── routes/occupations.py    US-1.1 occupation search
│   └── schemas/occupation.py    Pydantic response models — not yet written
├── database/
│   ├── connection.py        SQLAlchemy engine/session, reads DATABASE_URL
│   └── schema.sql           Source of truth for the DB schema
├── etl/                     Extract/clean scripts + the database loader
├── tests/                   Unit tests for the ETL scripts
├── datasets/                Raw source files — gitignored, not committed
├── data/processed/          Cleaned ETL output — committed
├── .env.example             Template for your local .env
└── requirements.txt
```

---

### Chatbot backend structure

| File | Responsibility |
|---|---|
| `app/routes/chat.py` | `POST /api/v1/chat` routing and HTTP error handling |
| `app/schemas/chat.py` | Request/response validation and public API contract |
| `app/services/chat_intent.py` | Deterministic English body-region and job-comparison intent parsing |
| `app/services/occupation_demand_search.py` | Cross-occupation BOHD comparison using Sam's existing body-region mapping |
| `app/services/chat_context.py` | Read-only PostgreSQL context and source metadata assembly |
| `app/services/rag_retriever.py` | Local FAISS loading, integrity checks, filtering, and Top-K retrieval |
| `app/services/nvidia_chat.py` | NVIDIA NIM client, system boundary, and deterministic answer formatting |
| `knowledge/telosia_chat_knowledge.md` | Site scope, terminology, and data limitations supplied to the answer layer |
| `knowledge/rag/` | Committed JSONL chunks, FAISS vectors, and manifest used at runtime |
| `scripts/build_rag_documents.py` | Build reviewed chunks from the local annotation workbook |
| `scripts/build_rag_index.py` | Generate embeddings and rebuild the FAISS index |
| `tests/test_chat.py` | Endpoint, scope, response, grounding, and failure-path tests |
| `tests/test_occupation_demand_search.py` | Intent-to-database occupation-ranking tests |

---

## Local setup

```bash
git clone https://github.com/abdullahmehmood0/telosia.git
cd telosia
git switch Backend

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Database** (PostgreSQL 18, or close to it):

```bash
createdb telosia
psql -h localhost -d telosia -f database/schema.sql
```

**Environment** — copy `.env.example` to `.env` and fill in your local Postgres credentials:

```env
DATABASE_URL=postgresql+psycopg://your_username:your_password@localhost:5432/telosia
NVIDIA_API_KEY=nvapi-your-api-key
NVIDIA_API_BASE=https://integrate.api.nvidia.com/v1
NVIDIA_CHAT_MODEL=openai/gpt-oss-20b
RAG_INDEX_DIRECTORY=knowledge/rag
RAG_MINIMUM_SCORE=0.30
RAG_ALLOW_UNREVIEWED=false
```

If your local Postgres role has no password, drop that part: `postgresql+psycopg://your_username@localhost:5432/telosia`.

**Run it:**

```bash
fastapi run app/main.py
```
Swagger UI at `http://127.0.0.1:8000/docs`.

### Loading real data (optional, for testing against non-empty tables)

The cleaned datasets are committed under `data/processed/*.csv` — cloning the repo gets you real data, no ETL run required first. Load them with:

```bash
python3 -m etl.load_database
```

Run it as a module (`-m`), not `python3 etl/load_database.py` — running it directly breaks the `database` import.

---

## Database schema

`database/schema.sql` is built and validated directly against the project's real datasets (not purely from the ERD) — 11 tables in the `telosia` schema:

| Table | Holds |
|---|---|
| `source_reference` | Provenance for every dataset (publisher, licence, coverage period, plain-language note) |
| `occupation` | One row per 4-digit ANZSCO code — `occupation_id` (`SERIAL`), `anzsco_code`, `occupation_title` |
| `occupation_profile` | JSA employment/earnings/education data per occupation |
| `injury_frequency` | Safe Work Australia WCIFR — lost-time claims per million hours worked |
| `hazard_variable` / `hazard_exposure` | BOHD's 57 hazard variables and each occupation's exposure score |
| `mobility_flow` | Observed occupation-to-occupation transitions (JSA) |
| `occupation_alias` | Plain-language search terms per occupation — 3,118 rows: 3,116 from the ABS's official ANZSCO alias index, 2 hand-curated (see below) |
| `crosswalk_status` | ASCO2 ↔ ANZSCO mapping status/confidence — for the WorkSafe Victoria crosswalk |
| `model_run` / `injury_insight` | For later trend/AI-signal features — not populated yet |

**Not modelled yet, deliberately:** WorkSafe Victoria's ASCO2-coded injury claims. They can't be joined against the ANZSCO-coded data above until the ASCO2→ANZSCO crosswalk is verified across all 341 occupations (open blocker on the Scrum board, not a backend task).

Primary keys are `SERIAL` throughout — the ETL loader lets Postgres assign IDs rather than assigning them itself.

---

## API

All occupation routes are under `/api/v1` (adopted to match the frontend's `API_REQUIREMENTS.md`; there's no unprefixed version anymore — nothing depended on the old path when this changed).

| Endpoint | Status |
|---|---|
| `GET /` | ✅ |
| `GET /health` | ✅ — checks DB connectivity |
| `GET /api/v1/occupations/search?q=` | ✅ US-1.1 |
| `GET /api/v1/occupations/{id}` | ✅ US-1.2 |
| `GET /api/v1/occupations/{id}/injury-profile` | not built — blocked on WorkSafe Vic data (US-2.1/2.2 proper: real injury *claims* proportions) |
| `GET /api/v1/occupations/{id}/body-regions` | ✅ — physical-demand *exposure* (BOHD), not blocked, not the same thing as the above |
| `GET /api/v1/occupations/{id}/destinations` | ✅ US-3.1 |
| `GET /api/v1/occupations/{id}/destinations/{destination_id}` | ✅ US-3.2 |
| `GET /api/v1/occupations/{id}/ai-exposure` | ✅ US-7.1 / AC7.1 — published JSA Gen AI exposure ratings, not modelled |
| `GET /api/v1/occupations/{id}/pay-gap` | ✅ US-4.1 / AC4.1-a / AC4.1-b — published JSA gender pay gap, per 6-digit specialisation |
| `GET /api/v1/occupations/{id}/injury-insight` | ✅ — a research model's *tier* (direction only, never a number), not published claims data — see below |
| `POST /api/v1/chat` | ✅ — deterministic occupation comparison, local RAG, PostgreSQL context, and NVIDIA NIM |
| `GET /api/v1/sources`, `/sources/{id}` | ✅ US-6.1/6.2 |

### `POST /api/v1/chat`

The chatbot is a bounded Telosia assistant, not an unrestricted general-purpose
agent. It combines deterministic English intent parsing, live read-only
PostgreSQL queries, a local FAISS knowledge index, and NVIDIA NIM. The current
implementation has no autonomous tool calling and performs no database writes.

Supported capabilities:

- explain Telosia datasets, terminology, sources, and limitations;
- answer occupation-specific questions using the selected occupation's
  profile, physical-demand exposure, injury-frequency averages, and observed
  mobility destinations;
- retrieve approved hazard-to-body association material from the local RAG
  index;
- compare occupations with higher or lower recorded BOHD exposure for one or
  more supported body regions; and
- return structured occupation results and source metadata for the frontend.

Explicitly unsupported:

- medical diagnosis, treatment, medication, or emergency instructions;
- deciding whether a job is medically suitable for an individual;
- presenting BOHD exposure as observed injury, causation, or personal risk;
- claims by body part by occupation, because the published source does not
  provide that measure; and
- inventing, interpolating, or replacing missing published values with zero.

#### Request contract

```json
{
  "message": "What physical demands affect the lower back?",
  "occupation_id": 237
}
```

| Field | Type | Required | Validation |
|---|---|---|---|
| `message` | string | yes | Trimmed, 2-500 characters, cannot be blank |
| `occupation_id` | positive integer or `null` | no | Must refer to an existing occupation when supplied |

Example without a selected occupation:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Which jobs have low exposure for the lower back?"}'
```

Example for the occupation currently selected by the frontend:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"What is the injury frequency rate for this occupation?","occupation_id":237}'
```

#### Request-routing flow

```text
Validated ChatRequest
        |
        v
Scope guard (Telosia topics only)
        |
        +--> unsupported topic -> out_of_scope (no model call)
        |
        v
English body-region/job-comparison intent parser
        |
        +--> matched -> Sam's region mapping + approved RAG hazard IDs
        |              + PostgreSQL BOHD scores -> structured occupations
        |              (deterministic; no model call)
        |
        v
Occupation-required check
        |
        +--> missing occupation -> needs_occupation (no model call)
        |
        v
Local FAISS Top-5 retrieval + optional live occupation context
        |
        v
Deterministic body-mapping answer when supported,
otherwise bounded NVIDIA NIM generation
        |
        v
ChatResponse with answer, occupation results, and sources
```

The cross-occupation path recognises English variants for six regions:

- Lower back
- Shoulders and upper arms
- Hands and wrists
- Knees
- Legs and feet
- Whole body and fall risk

Questions expressing a limitation, such as `I have an issue with my lower
back; what kind of job should I choose?`, are interpreted as a request for
occupations with **lower recorded exposure**, not as a medical assessment.
Questions such as `Which jobs use the hands most?` are interpreted as a
higher-exposure comparison. The route returns at most four occupations.

For each candidate, the backend:

1. resolves Sam's existing `BODY_REGION_MAPPING` variable names to approved
   hazard IDs in the RAG metadata;
2. reads the corresponding occupation exposure scores from PostgreSQL;
3. takes the maximum contributing variable for each region, matching the body
   map calculation;
4. takes the maximum across requested regions when more than one is supplied;
5. rounds the comparison score to a whole number; and
6. excludes occupations that do not have a published contributing measure.

The result is an exposure comparison only. It is not a recommendation that a
job is safe or clinically suitable for a person.

#### Response contract

| Field | Meaning |
|---|---|
| `status` | One of `answered`, `out_of_scope`, `needs_occupation`, or `temporarily_unavailable` |
| `answer` | Plain-English/Markdown answer or a fixed boundary/error message |
| `occupation_id` | Selected occupation ID, or `null` for a cross-occupation result |
| `occupation_results` | Structured comparison cards for deterministic higher/lower exposure searches |
| `sources` | Publisher, dataset, URL, licence, coverage dates, retrieval date, and plain-language note |

Each `occupation_results` item contains:

```json
{
  "occupation_id": 42,
  "title": "Example occupation",
  "comparison": "lower",
  "relative_exposure_score": 18,
  "body_regions": ["Lower back"],
  "leading_demands": ["Spend Time Sitting"]
}
```

The example above documents the response shape only; it is not a published
Telosia result. Actual values always come from the current database.

Response behaviour:

| Situation | HTTP | Chat `status` |
|---|---:|---|
| Supported and answered | 200 | `answered` |
| Unrelated request or a request containing a configured diagnosis/treatment/medication/emergency term | 200 | `out_of_scope` |
| An occupation-specific measure was requested without an occupation | 200 | `needs_occupation` |
| NVIDIA rate limit, connection failure, or upstream API failure | 200 | `temporarily_unavailable` |
| Missing NVIDIA configuration or invalid/inconsistent RAG artifacts | 503 | FastAPI error detail |
| Invalid request body | 422 | FastAPI validation detail |
| Unknown supplied occupation ID | 404 | FastAPI error detail |

#### Context sent to NVIDIA NIM

The model does not connect to PostgreSQL, FAISS, or the frontend directly. The
backend constructs `TELOSIA_CONTEXT` before the model request. Depending on the
question, that context contains:

- the reviewed site knowledge boundary;
- up to five filtered RAG matches;
- the selected occupation profile and tasks;
- Sam's calculated body-region exposure data;
- injury-frequency all-year and latest-five-financial-year **averages**;
- observed occupation mobility destinations; and
- supporting source metadata.

The system prompt instructs the model to treat context as data rather than
instructions, name a selected occupation, distinguish a general mapping from
an occupation-specific result, and refuse to invent missing values. The
default request uses temperature `0.2`, a maximum of `600` output tokens, a
30-second timeout, and one retry.

The NVIDIA API key remains in the backend `.env`. It must never be committed or
sent to the browser.

#### Local RAG knowledge base

Runtime artifacts live in `knowledge/rag/`:

| Artifact | Purpose |
|---|---|
| `documents.jsonl` | Text chunks and structured metadata |
| `index.faiss` | Normalised 384-dimensional vectors searched by inner product/cosine similarity |
| `manifest.json` | Embedding model, counts, ordered chunk IDs, dimension, timestamp, and SHA-256 integrity data |

The current index uses `sentence-transformers/all-MiniLM-L6-v2` and contains
127 chunks: 80 hazard/body-association chunks, 42 body-part lookup chunks, and
5 methodology chunks. At runtime, `RAG_ALLOW_UNREVIEWED=false` allows approved
project records and methodology references only. Project approval is a content
workflow status; it is not clinical validation.

When a body-part term is recognised, retrieval searches the small full index
and then filters by compatible TOOCS body codes. Otherwise it retrieves a
larger candidate set before returning the best five results. The default
minimum cosine-similarity score is `0.30`. Similarity is textual relevance,
not an injury-risk or association score.

The retriever validates all three artifacts when it loads:

- `documents.jsonl` SHA-256 must match the manifest;
- document order must match the manifest's ordered chunk IDs;
- document, manifest, and FAISS vector counts must agree; and
- FAISS vector dimension must match the manifest.

The retriever and embedding model are cached once per backend process. These
local RAG files do not add or modify PostgreSQL tables.

#### Rebuilding the RAG artifacts

The committed artifacts are ready for normal runtime use. Rebuilding is only
required after changing the annotation source or chunking logic. The source
workbook is local and gitignored at:

```text
data/annotation/occupational_hazard_body_part_annotations_all_57_english.xlsx
```

Rebuild in this order from the repository root:

```bash
python scripts/build_rag_documents.py
python scripts/build_rag_index.py
```

For local review work only, unreviewed annotation records can be included with:

```bash
python scripts/build_rag_documents.py --include-unreviewed
```

That option should be paired with `RAG_ALLOW_UNREVIEWED=true` only in an
explicit local review environment, never silently enabled for deployment.
After changing `documents.jsonl`, always rebuild `index.faiss` and
`manifest.json`; otherwise the integrity check deliberately returns a RAG
configuration error.

#### Chatbot tests

The chatbot tests do not require a live NVIDIA request. Model and database
boundaries are replaced with controlled test doubles.

```bash
python -m pytest tests/test_chat.py tests/test_occupation_demand_search.py -q
```

### `GET /api/v1/occupations/search?q=`

Plain-language occupation search, tried as three tiers, each only reached if the previous one finds nothing:

1. **Exact → prefix → substring match**, against both `occupation.occupation_title` and `occupation_alias.alias_text`. Handles most typed queries, including single-word synonyms once loaded as an alias (`"cop"` → Police).
2. **Full-text search** (`to_tsvector`/`to_tsquery`, OR-combined terms, ranked by `ts_rank`) — for multi-word or voice-style queries that don't appear as a literal substring anywhere, e.g. `"I work as an electrician"` or `"aged care worker"` against the alias `"Registered Nurse (Aged Care)"`.
3. **Trigram similarity** (`pg_trgm`, title only) — for single-word typos/misspellings of an occupation's title, e.g. `"nurrse"`, `"plummer"`, `"electrican"`.

All capped at 10 results. Tier-2/3 responses carry a `message` noting the match wasn't exact; tier 1 doesn't.

```
GET /api/v1/occupations/search?q=carer
```
```json
{
  "query": "carer",
  "count": 3,
  "matches": [
    { "occupation_id": 237, "title": "Aged and Disabled Carers" },
    { "occupation_id": 234, "title": "Child Carers" },
    { "occupation_id": 236, "title": "Personal Carers and Assistants nfd" }
  ],
  "fallback_available": true,
  "message": null
}
```

`q` requires 3–100 characters (422 otherwise). If no tier matches, `matches`
stays empty and `fallback_suggestions` contains up to five occupations ranked
from real WCIFR records. These alternatives are kept separate because they do
not match the user's search text. If the database cannot produce suggestions,
`fallback_available` is `false` and the response contains the ordinary no-match
message.

### Where `occupation_alias` data comes from

Two sources, kept honestly distinct rather than blurred together:

1. **ABS's official "ANZSCO 2022 Index of Principal Titles, Alternative Titles and Specialisations"** (`etl/anzsco_alias_etl.py`) — a real, citable government publication, registered in `source_reference` like every other dataset. 86% of our 401 loaded occupations get real coverage from it (3,116 rows). This is where terms like "developer" and "programmer" resolve correctly to real occupations.
2. **A small, hand-curated list** (`CURATED_ALIASES` in `etl/load_database.py`) for genuine informal/slang terms the official index doesn't recognise — currently just `cop` → Police and `coder` → Software and Applications Programmers, each with a documented reason in the code, found through actual search testing rather than guessed in advance. Deliberately kept small and reviewable rather than a long invented list.

**Also found and worth knowing:** adding more alias text increases the chance of short, coincidental substring collisions - e.g. "cop" is a literal substring of "Copywriter," "Copyist," "helicopter," and "photocopier," none of which are related. This is why `cop` returns 7 results, not 1 - the coincidental matches aren't removed, but the curated alias means the correct answer (Police) now ranks first.

**Trigram (tier 3) is deliberately title-only, not title+alias.** Comparing against every individual alias too was tried and reverted: live testing found "plummer" matching "Music Professionals" (via its "Drummer" alias, 0.333 similarity - a coincidental collision, the same dynamic as "cop"/Cooks, just recurring because short alias strings have few distinguishing trigrams) ranked *ahead of* "Plumbers" itself. Comparing against one combined title+aliases document per occupation instead of each alias individually was also tried - that made every score collapse toward zero and penalised occupations with the richest alias coverage the most. Title-only trades some recall (a typo of a specific alias phrase, rather than the title, won't be caught) for not surfacing results like that. The similarity threshold (0.28) is calibrated against real data: genuine typos of a title score 0.29-0.57, while the known "cop"/Cooks-style collision scores 0.25.

### `GET /api/v1/occupations/{id}`

Single occupation lookup — US-1.2, confirming a selection before risk data loads.

```
GET /api/v1/occupations/237
```
```json
{
  "id": 237,
  "title": "Aged and Disabled Carers",
  "aliases": ["Aged or Disabled Care Worker", "Aged or Disabled Carer", "Personal Care Worker", "Personal Carer"],
  "description": "Aged and Disabled Carers provide general household assistance, emotional support, care and companionship for aged and disabled persons in their own homes.",
  "tasks": ["Accompanying aged and disabled persons during daily activities", "Assisting clients with their mobility", "..."]
}
```

`description` is `null` and `tasks` is `[]` for the 43 source-only occupation codes that aren't backed by a JSA occupation profile — never a fabricated placeholder. Unknown id → `404` with `{"detail": "No occupation found with id <id>."}`.

### `GET /api/v1/occupations/{id}/destinations`

Real destinations from JSA mobility data — US-3.1. Self-transitions (staying in the same job) are excluded. Ranked by share, top 10 returned; `share` is computed against the *true* total across every destination, not just the ones returned (an earlier version got this wrong — capped the SQL at 10 rows before summing for the percentage, which inflated every share whenever an occupation had more than 10 destinations; caught it by comparing against the detail endpoint for the same pair).

```
GET /api/v1/occupations/237/destinations
```
```json
{
  "occupation_id": 237,
  "is_fallback": false,
  "group": null,
  "destinations": [
    { "occupation_id": 134, "title": "Registered Nurses", "share": 22.5, "source_id": 4, "tag": "Most common move" }
  ]
}
```

**AC3.1-b fallback:** 2 of 401 loaded occupations (both "nfd"/"Other" catch-all ANZSCO codes) have no outbound mobility data of their own. For those, this aggregates destinations from other occupations sharing the same 3-digit ANZSCO minor group — the classification's actual next level up, not an invented grouping — and returns `is_fallback: true` with `group` describing it.

**Not in this response:** `tasks` per destination, which the frontend's `API_REQUIREMENTS.md` expects. `occupation_task` is now loaded (see `GET /occupations/{id}`) and a destination is just another occupation, so this is wirable — it just hasn't been done for this endpoint yet.

### `GET /api/v1/occupations/{id}/destinations/{destination_id}`

Destination detail — US-3.2. `share` here is specific to this exact source→destination pair (same figure the list endpoint shows for that pair). 404s if either occupation doesn't exist, or if no transition between them is recorded.

```
GET /api/v1/occupations/237/destinations/134
```
```json
{ "occupation_id": 134, "title": "Registered Nurses", "share": 22.5, "source_id": 4 }
```

### `GET /api/v1/sources`, `GET /api/v1/sources/{id}`

Provenance — US-6.1/6.2. `source_id` on any figure elsewhere in the API (e.g. `destinations[].source_id`) points here. `plain_language_note` is the AC6.2 field — verified under 60 words for all 4 currently loaded sources (longest is 19 words), not just assumed.

```
GET /api/v1/sources/4
```
```json
{
  "source_id": 4,
  "publisher": "Jobs and Skills Australia",
  "dataset_title": "Data on Occupation Mobility - Occupation Flows",
  "dataset_url": "https://www.jobsandskills.gov.au/publications/data-occupation-mobility-unpacking-workers-movements",
  "licence": "CC BY 4.0",
  "coverage_period_start": null,
  "coverage_period_end": null,
  "retrieval_date": "2026-09-03",
  "update_frequency": "Periodic",
  "plain_language_note": "Observed occupation transitions. The dataset covers workers generally and does not support claims that women specifically made these transitions."
}
```

**Known gap:** `coverage_period_start`/`coverage_period_end` are `null` for every source — `etl/load_database.py` never populates those two columns, even though the schema has them and AC6.1-a wants coverage period shown. Not fixed here; would mean going back to each raw dataset to find the actual coverage dates and adding that to the loader.

While building this, found and fixed a real, live data bug unrelated to the endpoint itself: source #3's `plain_language_note` still read "excluded from **WayOut** predictors" in both the local and the live Supabase database — the source string in `load_database.py` was fixed during the September rename work, but the loader was never re-run afterward, so the already-loaded row never picked up the fix. Re-ran the loader against both databases (it's an upsert, so this only refreshed the text — no duplicate rows, all counts unchanged) before shipping this PR.

### `GET /api/v1/occupations/{id}/body-regions`

Physical-demand exposure by body region, from BOHD. **This is not injury data** — a high score means the occupation scores highly on BOHD work-context variables associated with that body region (bending, standing, repetitive motion, etc.), not that Safe Work Australia recorded actual injuries there. Wording is deliberate throughout: "exposure," never "injury" or "risk." Mapping and approach designed by Sam (see `Telosia_Body_Region_Backend_Implementation.md`); no schema change, computed fresh from `hazard_variable`/`hazard_exposure` on every request, nothing derived is stored.

Six fixed regions, each backed by a curated set of BOHD variables (all 9 "Body Positioning" variables plus 4 others judged physically relevant — cramped space, vibration, high places, minor cuts). A region's score is the **maximum** among its available variables, not an average — averaging would dilute a single genuinely high exposure with unrelated lower ones.

```
GET /api/v1/occupations/237/body-regions
```
```json
{
  "occupation_id": 237,
  "title": "Aged and Disabled Carers",
  "body_regions": [
    {
      "region": "Lower back",
      "score": 62.5,
      "contributors": [
        { "variable": "Spend Time Bending or Twisting the Body", "score": 62.5 },
        { "variable": "Spend Time Sitting", "score": 22.75 }
      ],
      "message": null
    }
  ]
}
```

**No BOHD coverage for this occupation** (roughly 83 of 401 loaded occupations — BOHD only covers 318): every region comes back `score: null`, `contributors: []`, and an honest `message` explaining why — never a bare `0`, which could wrongly imply "no exposure" rather than "no data." The message is deliberately different from what AC2.1-b's claims-reporting-floor case will eventually say — this occupation genuinely isn't in the dataset at all, versus AC2.1-b's case where data exists but is too small a count to report reliably. Different truths, different wording.

The response also carries `overall_exposure_percentile`: this occupation's average BOHD exposure, ranked against its own destination occupations specifically (the same set `/destinations` would show it), not the whole 401-occupation population. Straight from published data, no model involved — `null` if either side has no BOHD coverage to compare.

### `GET /api/v1/occupations/{id}/ai-exposure`

Published generative AI exposure ratings, from JSA's Generative AI Capacity Study — US-7.1 / AC7.1. **Published research only, nothing modelled by the team.** `automation_exposure` and `augmentation_exposure` are both 0–1. Every response carries a fixed `message` stating exposure is not the same as displacement — this is a permanent caveat shown alongside real data, not just a fallback for missing data (that's AC7.1's actual requirement, not an afterthought).

```
GET /api/v1/occupations/237/ai-exposure
```
```json
{
  "occupation_id": 237,
  "title": "Aged and Disabled Carers",
  "occupation_matrix_group": "Health and Community Services",
  "automation_exposure": 0.21,
  "automation_sd": 0.09,
  "augmentation_exposure": 0.47,
  "augmentation_sd": 0.17,
  "rate_of_skill_change": 2.5,
  "high_fit_transition_rate": 0.01,
  "entry_level_ad_share": 0.17,
  "source_id": 37,
  "message": "Exposure indicates potential for tasks to be performed or assisted by generative AI, based on published research. It is not a forecast that this occupation will be automated away or that workers will be displaced."
}
```

**No rating published for this occupation** (44 of 401 loaded occupations — coverage is 357): every field comes back `null` except `occupation_id`, `title`, and a `message` saying so — same honesty pattern as body-regions, no invented score.

### `GET /api/v1/occupations/{id}/pay-gap`

Published gender pay gap figures, from JSA's Occupational Gender Pay Gap Dashboard — US-4.1 / AC4.1-a / AC4.1-b. Published at 6-digit ANZSCO, one level finer than Telosia's 4-digit occupations, so one occupation can return several **specialisations** — deliberately never averaged or picked down to one number. 175 of 340 covered occupations have exactly one specialisation; the rest have several, and the difference between them is real: Registered Nurses alone has 13, ranging from 0.140 to 0.368 gender pay gap depending on which one.

Only the "Whole workforce" headline cohort is returned per specialisation, not the four age-band cohorts also held in the data — a scope decision, not an oversight.

```
GET /api/v1/occupations/237/pay-gap
```
```json
{
  "occupation_id": 237,
  "title": "Aged and Disabled Carers",
  "specializations": [
    {
      "anzsco_6digit_code": "423111",
      "anzsco_6digit_title": "Aged or Disabled Carer",
      "segregation_intensity": "Highly female dominated",
      "female_income_median": 53920.0,
      "male_income_median": 68120.0,
      "gender_pay_gap": 0.208,
      "hours_difference": 0.11,
      "ten_year_pay_gap": 0.215
    }
  ],
  "source_id": 29,
  "message": null
}
```

**No pay gap data at all for this occupation** (61 of 401 loaded occupations — coverage is 340 parent occupations): `specializations: []` and an honest message, same pattern as everywhere else. **AC4.1-b (never estimate a withheld figure)** needs no special handling — the underlying columns are already nullable, and JSA-withheld figures (real: 175 of 3,440 pay gap rows have at least one withheld field) pass through as `null`, never filled in.

### `GET /api/v1/occupations/{id}/injury-insight`

A research model's output, not a published statistic. Predicts an occupation's injury-frequency rate from its 57 BOHD exposure scores (training details: `model/README.md`; real evaluation numbers: `model/artifacts/metrics.json`) — but the model's absolute predictions failed validation (held-out test R² is negative), so **the raw number is never returned**, only which third it falls into relative to other occupations, where the model's ranking does hold up (test Spearman 0.77, 81% pairwise direction accuracy).

Scored **in-process**, on every request, by `app/services/injury_model.py` — the trained model (`model/artifacts/research_model.joblib` + `metrics.json`) loads once when the API starts, in the same process, no separate service or network call involved. If that load ever fails (missing/corrupt artifact), the module logs a warning and every occupation just gets the same honest "no estimate" response below — it does not take down the rest of the API. `GET /destinations` and `GET /destinations/{id}` also carry a `tier` field per occupation, scored the same way.

```
GET /api/v1/occupations/237/injury-insight
```
```json
{
  "occupation_id": 237,
  "title": "Aged and Disabled Carers",
  "insight": {
    "tier": "Higher than typical",
    "model_name": "exposure_injury_association",
    "model_version": "ridge-2026-09-17",
    "generated_at": "2026-09-17T10:22:53.420634+00:00"
  },
  "message": null
}
```

**No BOHD coverage for this occupation, or the model failed to load** (same ~83-of-401 coverage gap as `/body-regions`, since both read the same `hazard_exposure` data): `insight: null` and an honest message — never a fabricated tier.

### Frontend contract

The frontend's own `API_REQUIREMENTS.md` (on the `frontend` branch) documents the full expected shape. Adopted so far: the `/api/v1` prefix. Not yet adopted: camelCase field names, `{items, count}` response shapes, and string slug ids (frontend expects `"id": "personal-care-assistant"`; this API uses the real integer `occupation_id` as `id`, since that's the actual primary key and what `/search` already returns — no slug column exists, and building one wasn't judged worth it yet). **Correction from an earlier version of this README:** the frontend has since started calling this API for real (search and destinations views, confirmed live against `API_BASE = 'https://telosia.fastapicloud.dev/api/v1'`), not just running on local mock data.

### CORS

`app/main.py` allows `http://localhost:5173` and `http://127.0.0.1:5173` by default (the frontend's Vite dev server). The deployed app's actual `CORS_ALLOWED_ORIGINS` (set via `fastapi cloud env set`, not this default) currently allows:

```env
CORS_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,https://wayout-1lp6.onrender.com,https://telosia.online,https://www.telosia.online
```

`wayout-1lp6.onrender.com` is the frontend's actual Render service (still under its old slug); `telosia.online`/`www.telosia.online` is the custom domain pointed at that same service via DNS. Update the env var (delete then re-set — `env set` refuses to overwrite an existing variable) and redeploy whenever the frontend gets a new origin, no code change needed.

---

## Deployment

**API:** [FastAPI Cloud](https://fastapicloud.com), app `telosia`, deployed with `fastapi cloud deploy`. Requires `fastapi[standard]` in `requirements.txt` (not bare `fastapi`) — that's what provides the `fastapi` CLI the platform runs.

**Database:** Supabase Postgres, connected via FastAPI Cloud's Supabase integration. Use the **Session pooler** connection string, not the direct one — Supabase's direct-connection host resolves to an IPv6-only address that FastAPI Cloud's network can't reach.

**Env vars** (`fastapi cloud env list` / `env set` / `env delete --yes`, not a `.env` file — FastAPI Cloud never reads this repo's `.env`):

| Variable | Secret |
|---|---|
| `DATABASE_URL` | yes — Supabase pooler connection string |
| `CORS_ALLOWED_ORIGINS` | no |
| `NVIDIA_API_KEY` | yes - NVIDIA Developer API key |
| `NVIDIA_API_BASE` | no - defaults to `https://integrate.api.nvidia.com/v1` |
| `NVIDIA_CHAT_MODEL` | no - defaults to `openai/gpt-oss-20b` |
| `RAG_INDEX_DIRECTORY` | no - defaults to `knowledge/rag` |
| `RAG_MINIMUM_SCORE` | no - defaults to `0.30` cosine similarity |
| `RAG_ALLOW_UNREVIEWED` | no - defaults to `false`; local review only when enabled |

To redeploy after a change: `fastapi cloud deploy`.

---

## Where things actually are

Per the Scrum board's own Definition of Done, a story isn't Done until every AC card is verified — none currently are. Functionally:

- **US-1.1** (search): working, verified against real loaded data (401 occupations), with real alias coverage, full-text search, trigram typo tolerance, and AC1.1-b zero-result suggestions drawn from WCIFR data (see `occupations/search` above).
- **US-1.2** (confirm job): working, now also returning `description` and `tasks` where loaded (43 source-only codes have neither).
- **US-3.1/3.2** (destinations): working, including the AC3.1-b fallback. Missing `tasks` per destination — the data exists (`occupation_task`) but isn't wired into this endpoint yet.
- **US-6.1/6.2** (sources): working. The loader derives `coverage_period_start`/`coverage_period_end` from loaded dated records where possible and leaves genuinely unsupported periods null rather than guessing.
- **US-2.1/2.2** (injury drill-down, real claims proportions): genuinely blocked on the ASCO2→ANZSCO crosswalk verification, not a backend priority choice. A first-pass crosswalk was built (see `crosswalk/`) and sent to Sampreet (the card's actual owner) for review — not applied to the database yet.
- **Body-region physical-demand exposure** (not a Scrum-numbered story — a complementary feature Sam designed, using BOHD data that's already loaded and doesn't need the crosswalk): working. Deliberately not presented as satisfying US-2.1 — it's exposure data, not injury claims, and the wording throughout says so.

**Not merged into `main`, on purpose:**
- `origin/Yu-backend-iteration1` — uses SQLAlchemy ORM models, Alembic, Docker, a repository layer. Contradicts this project's SQL-first, no-ORM decision; would need a deliberate team call to adopt instead.
- `origin/frontend` — a real Vue app, but merging it as-is would delete backend files that don't exist on its history. Needs a repo-layout decision (e.g. a `frontend/` subfolder) first.

---

## Contributing

`main` requires a PR (protected branch). Branch off `Backend` (or from `main` for anything unrelated to the historical backend track), open a PR, get it reviewed — self-approval is disabled by GitHub for PR authors.

Don't commit `.env` or raw datasets (`datasets/`) — both gitignored. Cleaned ETL output under `data/processed/` **is** committed on purpose (see above) — if you regenerate one of those CSVs, commit the change.
