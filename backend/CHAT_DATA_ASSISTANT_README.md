# Telosia Conversational Data Assistant

The assistant lets users explore the project's public data in natural language.
The language model decides which datasets to inspect, which records to retrieve,
and which comparisons or calculations are needed. Backend tools execute those
operations and return evidence for the answer.

A user can ask a new combination of questions without a new question-specific
Python function. For example, the same query tool can rank pay gaps, find lower
leg exposure, summarize injury rates, or compare regional employment.

## Architecture

```text
ChatBot.vue: current question + successful prior turns + optional occupation/page
  -> POST /api/v1/chat/stream (JSON /chat remains available)
  -> Static field hints + optional selection ID; no eager DB access
  -> NVIDIA model chooses a tool and arguments
       describe_data: optional inspection of unfamiliar fields/availability
       query_data: select, filter, group, aggregate, sort or page database records;
                   optionally calculate from those rows in the same call
       calculate: arithmetic using returned query cells
       search_knowledge: optional local document/evidence retrieval
  -> Validated execution returns evidence or a correctable error
  -> Model may issue another query or calculation
  -> Stage events/text deltas, then authoritative answer, sources and timings
```

The active route does not use the previous keyword scope filter, regex intent
parser or mandatory selected-occupation check. The model handles English
paraphrases and follow-up references. A selected occupation is context for “my
job,” not a mandatory filter for every query. Unclear measures may still need a
clarifying answer: a gender gap within an occupation and a salary difference
between occupations measure different things.

`chat_data.py` owns the public catalog and structured-query executor.
`chat_tools.py` owns the tool definitions, current request's results and
calculations. `nvidia_chat.py` owns the model/tool loop. `chat_context.py` supplies
cached local guidance and an optional selected occupation ID, with no profile
prefetch. The model receives compact static schema hints rather than the whole
site document on every turn. Data and RAG are fetched only on tool demand.
`routes/chat.py` and `schemas/chat.py` define the HTTP contract.

The model chooses operations, but receives no database credentials and cannot
submit SQL. SQLAlchemy resolves approved fields and binds values. PostgreSQL
queries use separate read-only transactions and a five-second statement
timeout. These changes do not create or modify database tables, columns,
migrations, ETL files or Sam's mapping. Existing legacy intent services can
remain on disk without controlling the new route.

## Data catalog

The registry describes 22 public research tables plus one derived dataset.
Initial static hints describe supported contracts, not confirmed loaded data.
On-demand `describe_data` advertises only registered tables present in the connected
`telosia` schema. A table may be present but contain no data. Source-only
occupations may lack profiles or other measurements.

Live catalogs are cached per SQLAlchemy engine for 300 seconds. The cache does
not cache business rows or require a startup database connection. Use
`clear_catalog_cache(engine)` after a schema change if immediate rediscovery
is required; otherwise the next expired catalog request refreshes reflection.

| Dataset | Observation grain / meaning |
|---|---|
| `occupation` | One four-digit ANZSCO occupation |
| `occupation_profile` | One published occupation profile: earnings, employment, demographics and qualifications |
| `occupation_task` | One ordered task per occupation |
| `occupation_alias` | One alternative occupation name |
| `source_reference` | One dataset's publisher, URL, licence and coverage |
| `injury_frequency` | One occupation, financial year and measure type |
| `hazard_variable` | One BOHD variable and its definition |
| `hazard_exposure` | One occupation and hazard-variable exposure score |
| `mobility_flow` | One source occupation, destination occupation and financial year |
| `pay_gap` | One six-digit specialisation and cohort |
| `ai_exposure` | One four-digit occupation's published AI indicators |
| `nds_category` | One NDS classification dimension and category |
| `nds_claim_statistic` | One category, financial year and measure, with unit |
| `occupation_nds_link` | Link from a four-digit occupation to its broader NDS category |
| `region` | One SA4 region and state |
| `regional_employment` | One occupation, SA4 region and reference date |
| `crosswalk_status` | One classification crosswalk record |
| `model_run` | One project's model run and provenance |
| `injury_insight` | One occupation, model run and insight type |
| `hazard_annotation` | One project's hazard annotation, evidence and review status |
| `hazard_body_part_mapping` | One annotated hazard/body-part association |
| `body_part_code` | One body-part classification code |
| `body_region_exposure` | Derived occupation/region scores using Sam's existing six-region mapping |

Common foreign keys are enriched with readable labels when their lookup tables
exist: occupation titles/codes, source/destination occupations, hazard names,
SA4/state names and NDS categories. Annotation associations can include body
labels and review evidence. Cross-dataset analysis uses these fields and
multiple queries with returned IDs; the tool does not accept arbitrary joins.

`body_region_exposure` is calculated at query time, not stored as a new database
table. Its fields include `occupation_id`, `occupation_title`, `anzsco_code`,
`region`, `score`, `available_variable_count`, `expected_variable_count` and
`complete_coverage`.

## Public chat API

The frontend sends `POST /api/v1/chat/stream`. `POST /api/v1/chat` remains a
compatible non-streaming JSON endpoint. Tool names below are internal model tools,
not separate HTTP endpoints.

```json
{
  "message": "Which occupations have the lowest exposure for legs and feet?",
  "occupation_id": null,
  "history": [],
  "page_context": "/risk"
}
```

`message` accepts 2–2,000 characters, trims surrounding whitespace and rejects
blank text. `occupation_id` is optional; if supplied it must be a positive ID
that exists. `history` accepts at most ten `{role, content}` messages, with
`role` equal to `user` or `assistant` and content of 1–4,000 characters.
`page_context` is an optional string of at most 120 characters.

The frontend stores successful user/assistant exchanges in browser memory and
sends the last ten messages before the new question. It excludes the greeting
and unsuccessful requests. Changing occupation clears the history sent to the
model while keeping the visible conversation. It also sends the router's path.
Neither history nor page context proves a fact: follow-up calculations retrieve
current records again. The path does not itself transmit every UI filter or the
currently opened destination card.

The response includes:

```json
{
  "status": "answered",
  "answer": "An answer grounded in the returned records.",
  "occupation_id": null,
  "occupation_results": [],
  "sources": [],
  "tools_used": ["describe_data", "query_data", "calculate"],
  "data_queries": [
    {"query_id": "q1", "dataset": "pay_gap", "row_count": 2, "truncated": true}
  ]
}
```

This example shows structure only. `sources` normally contains the supporting
database source metadata when the results have source references. Query traces
record successful queries; `tools_used` also records attempted calls, including
errors and repeats. `truncated: true` means more matching results exist than the
requested page, not that the top-ranked rows were computed from a sample.

The `occupation_results` field remains for API compatibility but is empty in
this general analysis flow. Intermediate query candidates are not automatically
shown as recommendations: later queries may eliminate them. Relevant occupation
names appear in the final answer. The frontend displays the answer and sources;
query traces are available in the API response for inspection.

## Streaming and latency diagnostics

Use `POST /api/v1/chat/stream` with the same request body as `/chat`. The
response is `text/event-stream`; reverse proxies must not buffer the stream.
The application sends these events:

| Event | Payload and frontend behaviour |
|---|---|
| `status` | `{request_id, stage, message}`. Stages distinguish understanding, querying, searching, calculating, generating and retrying. |
| `delta` | `{text}` plus request ID. Append provisional answer text, not reasoning or tool arguments. |
| `answer_reset` | Clear provisional text when a round calls tools or fails. |
| `data_result` | Completed query preview; retain on errors, group by dataset and collapse by default. |
| `result` | Full `ChatResponse`. Save completed answers normally; save partial turns as incomplete-status summaries. Includes a signed `turn_token` for next-turn metadata. |
| `error` | `{request_id, error_code, message}` for failures after stream headers. Do not retain provisional output as a successful answer. |

Comment heartbeats keep the connection active while the provider is thinking.
The frontend follows the advertised server deadline plus 15 seconds (maximum
315 seconds), aborts when unmounted, or when the user presses
**Stop**. It does not automatically retry the HTTP request or fall back to
`/chat`, preventing duplicate model runs. The backend closes the request's
model client on cancellation; a currently executing DB operation must still
settle under its database/connection timeout.

Responses include `request_id`, `elapsed_ms`, `timings`, and optional
`error_code`/`error_stage`. Timing entries measure model attempts, first provider
activity (`first_model_event`, tagged as text/tool/reasoning), first visible text,
tools and the whole request. Reasoning text is never stored or displayed.
Server logs use the same request ID and contain
only execution metadata, not messages, query rows or API keys. For example:

```text
chat_timing request_id=... stage=model elapsed_ms=... round=1 attempt=1 outcome=APITimeoutError
chat_timing request_id=... stage=tool elapsed_ms=... tool=query_data outcome=completed
```

An empty `tools_used`/`data_queries` with a model timeout means no data tool
completed; it is not proof that the database was still loading. A short first
status event is also not the same as a fast model answer. No guarantees about
provider queueing or uptime are implied by the local improvements.

The implementation follows the official [streaming function-call delta
contract](https://developers.openai.com/api/docs/guides/function-calling#streaming):
tool-call fragments are accumulated by index and executed only after the model
round completes. It remains on the existing NVIDIA endpoint and model.

## General query contract

Use the supplied static field hints to query known fields directly. When needed,
call `describe_data` with `{}` for an overview, or with
`{"dataset":"pay_gap"}` for exact fields, units and grain. The model then uses
`query_data`:

```json
{
  "dataset": "pay_gap",
  "select": [
    "parent_occupation_id", "occupation_title", "anzsco_6digit_code",
    "anzsco_6digit_title", "cohort", "gender_pay_gap"
  ],
  "filters": [
    {"field": "is_headline_cohort", "op": "eq", "value": true},
    {"field": "gender_pay_gap", "op": "not_null"}
  ],
  "order_by": [{"field": "gender_pay_gap", "direction": "desc"}],
  "limit": 2
}
```

This finds the two highest published headline **specialisations**. It does not
silently convert a specialisation's maximum into its parent occupation's gap.
Two returned specialisations may share a parent. If the user specifically asks
for distinct four-digit groups, the answer must identify how those groups are
represented and what any grouped statistic means.

Supported query parameters are:

| Parameter | Behavior |
|---|---|
| `dataset` | Required registered name |
| `select` | Up to 35 field names; default is available fields for raw queries, group fields for aggregates |
| `filters` | Up to 20 `field/op/value` filters combined with AND |
| `group_by` | Up to 12 fields; selected raw fields must be group fields when aggregating |
| `metrics` | Up to 12 `{function, field, alias}` aggregations |
| `order_by` | Up to 8 `{field, direction}` items; `asc` or `desc`; NULL values sort last |
| `distinct` | Optional boolean for distinct raw rows |
| `limit` | 1–100 rows, default 20 |
| `offset` | 0–10,000, default 0 |

Filter operators are `eq`, `ne`, `gt`, `ge`, `lt`, `le`, `in`, `contains`,
`is_null` and `not_null`. `contains` is a case-insensitive literal-text search,
so `%` and `_` do not become user-controlled SQL wildcards. `in` takes 1–100
scalar values. Null checks need no value. Numeric/date/boolean filter values
must match their field types.

Metrics support `count`, `count_distinct`, `min`, `max`, `avg` and `sum`.
`count` without a field counts rows. Aliases must be unique identifiers and
cannot overwrite existing fields. Include every grouping field in `select` so
results and their source evidence remain identifiable. Queries return `rows`,
`query_id`, units, grain, provenance, truncation and pagination metadata.

## Calculations grounded in returned rows

Prefer attaching calculations to a new `query_data` call when the operands will
come from that query. This avoids asking the model for another round solely to
request arithmetic. For the preceding pay-gap query, add:

```json
{
  "calculations": [{
    "operation": "percentage_point_difference",
    "operands": [
      {"row": 0, "field": "gender_pay_gap"},
      {"row": 1, "field": "gender_pay_gap"}
    ]
  }]
}
```

This is an additional property on the query, not a standalone request. It
accepts at most five calculations. The backend first runs the validated query,
then resolves zero-based row/field operands against its actual result. It
returns rows, sources and `calculations` together. No guessed query ID or raw
numeric operand is accepted. Invalid arithmetic returns an error inside the
calculation result while preserving valid query evidence; missing cells never
become zero. The same unit, cohort, median and missing-value checks as the
standalone calculator apply. This does not alter the database query engine,
schema, ETL or Sam's mapping.

Use standalone `calculate` for cells already returned or for cross-query
comparisons. After the pay-gap query returns `q1`, the model can request:

```json
{
  "operation": "percentage_point_difference",
  "operands": [
    {"query_id": "q1", "row": 0, "field": "gender_pay_gap"},
    {"query_id": "q1", "row": 1, "field": "gender_pay_gap"}
  ]
}
```

Rows are zero-based. The operation above computes `(first - second) * 100`
because the stored pay gaps are fractions. For values already expressed in
percent, use `difference` and do not multiply again.

Other operations are `difference`, `absolute_difference`, `ratio`,
`percent_change`, `sum`, `mean`, `min`, `max` and `median`. `percent_change`
expects `[old, new]` and computes `(new - old) / old * 100`. Two-value operations
require exactly two operands. Each operand must reference an actual numeric
cell returned in the same request; the model cannot supply invented numeric
operands. Missing values and division by zero return an unavailable result.
The calculator checks units and required cohort/classification context. It
rejects pooling published medians and summing rates or exposure indices.
Regional employment sums must refer to the same snapshot date. These are
statistical validity checks, not a list of permitted user-question phrases.

Query IDs live only within one request. For a follow-up such as “What is the
difference between them?”, history helps identify the occupations, but the
model must query them again before calculating. Dataset-wide statistics belong
in query aggregates. A mean of a limited result page must not be described as a
mean of the entire dataset.

## Body-region example and statistical meaning

The tool executes ranking against original database scores and rounds returned
exposure indices to whole numbers before sending them to the model. Arithmetic
on those returned cells also uses the rounded values. The backend appends the
beta-release/U.S.-mapping and non-medical disclosure to exposure-query answers,
so that disclosure does not depend on the model remembering to include it.

For “Which jobs have the lowest risk for legs?”, the model interprets the
supported data question as lower recorded exposure and can issue:

```json
{
  "dataset": "body_region_exposure",
  "select": ["occupation_id", "occupation_title", "region", "score"],
  "filters": [
    {"field": "region", "op": "eq", "value": "Legs and feet"},
    {"field": "complete_coverage", "op": "eq", "value": true},
    {"field": "score", "op": "not_null"}
  ],
  "order_by": [{"field": "score", "direction": "asc"}],
  "limit": 4
}
```

The existing `BODY_REGION_MAPPING` in `app/routes/occupations.py` defines Lower
back, Shoulders and upper arms, Hands and wrists, Knees, Legs and feet, and Whole
body and fall risk. `score` is the maximum of each region's contributing BOHD
variables. `complete_coverage=true` prevents an occupation with missing
contributors from appearing artificially low in a low-exposure ranking.

Answers show rounded whole scores or explain bands. The body scores describe
work demands, not observed injury probabilities, clinical diagnoses or
individual job suitability. They also disclose BOHD's beta status and its
partial mapping of U.S. O*NET information to Australian occupations. Project
annotation weights and RAG relevance scores do not replace Sam's mapping.

The catalog and model instructions preserve these additional rules:

- `NULL` means missing or unpublished. It must not be replaced with zero.
- Gender pay gaps, AI automation and AI augmentation values are stored as
  fractions. Fields ending in `_pct` already represent percentages.
- Pay-gap cohort and six-digit specialisation remain explicit. Medians cannot
  be pooled into a parent median by averaging their published values.
- Yearly injury-frequency values are rates per million hours worked. Average
  compatible annual rates; never add the rates. Name the years used.
- NDS statistics require compatible measure, unit, dimension and classification
  level. A broader occupation-group value is not an individual occupation value.
- Regional employment records describe employment levels at a reference date.
  Adding multiple snapshots does not count unique workers or migration flows.
- AI exposure indicates task exposure, not a forecast that a job will disappear.
- Model insights and project annotations remain distinct from observed source
  measurements; preserve source attribution and review status.

The backend rejects a number of invalid combinations, such as summing rates or
mixing NDS units in a summary. The model still needs to select relevant filters
and explain an appropriate interpretation; passing validation alone does not
prove the user's intended statistical question was answered correctly.

## Optional knowledge retrieval

`search_knowledge` accepts `query` (2–500 characters) and optional `top_k` (1–5,
default 3). The tool loads `rag_retriever.py` only when requested. It is useful
for documented definitions, mapping evidence and limitations. Current numeric
values and rankings come from database queries.

Artifacts remain under `knowledge/rag/`: `documents.jsonl`, `index.faiss` and
`manifest.json`. The retriever uses the configured embedding model/index,
filters review status and validates artifact consistency. Similarity means
textual relevance, not risk or association strength. Missing or invalid RAG
artifacts yield an unavailable knowledge result without preventing database
queries.

To rebuild after changing source annotations, run from `backend/`:

```powershell
.\.venv\Scripts\python.exe scripts/build_rag_documents.py
.\.venv\Scripts\python.exe scripts/build_rag_index.py
```

The local source workbook is
`data/annotation/occupational_hazard_body_part_annotations_all_57_english.xlsx`.
`--include-unreviewed` on the document builder and `RAG_ALLOW_UNREVIEWED=true`
are options for an explicit local review workflow. Keep reviewed runtime
defaults otherwise. Rebuild vectors and the manifest whenever chunks change.

## Configuration and local checks

Copy settings from `.env.example` into the backend's local `.env`:

```env
NVIDIA_API_KEY=nvapi-your-api-key
NVIDIA_API_BASE=https://integrate.api.nvidia.com/v1
NVIDIA_CHAT_MODEL=deepseek-ai/deepseek-v4.1-flash
NVIDIA_CHAT_MAX_TOKENS=3072
NVIDIA_CHAT_TIMEOUT_SECONDS=60
CHAT_TOTAL_TIMEOUT_SECONDS=240
CHAT_SUMMARY_RESERVE_SECONDS=60
CHAT_EXTENDED_TIMEOUT_SECONDS=300
CHAT_MAX_TRANSIENT_RETRIES=1
CHAT_MAX_ROUNDS=7
CHAT_MAX_TOOL_CALLS=12
RAG_INDEX_DIRECTORY=knowledge/rag
RAG_MINIMUM_SCORE=0.30
RAG_ALLOW_UNREVIEWED=false
```

The existing `DATABASE_URL` continues to identify the database. The model key
belongs only in the backend environment. The selected provider/model must
support Chat Completions tool calls; configuration alone does not verify that
the external service is working.

The loop bounds rounds to 2–10, tool calls to 1–20 and output tokens per model
request to 512–8,192. Defaults are shown above. Each provider call has a
60-second socket timeout by default (configurable from 10 to 120 seconds).
`CHAT_TOTAL_TIMEOUT_SECONDS` defaults to 240 seconds (range 60–300) across the
analysis. The last 60 seconds are reserved for an evidence-only summary; an
explicit extended retry defaults to 300 seconds. The active model client is
closed on expiry; the SSE endpoint also ends after that budget plus a five-second
delivery allowance. An in-flight DB
operation still relies on its own database timeout and connection behaviour.
At most one transient model retry is allowed per user request, within the same
remaining budget, and only before receiving partial text/tool fragments.
Rate-limit responses and incomplete streams are not repeatedly replayed. When
the summary reserve is reached, new queries stop and the final round must finish
from available evidence. A stalled planning connection is closed at that boundary.
SDK automatic retries remain disabled; only the bounded application retry runs.
Multi-step questions still require several provider requests, so streaming does
not guarantee a fast first answer or remove external service delays.

From `backend/`, after installing `requirements-dev.txt` into its `.venv`:

```powershell
.\start_backend.cmd
```

This Windows launcher explicitly uses `backend/.venv` and `backend/.env`.
Local file values override stale shell settings. `.env.example` is a template,
not runtime configuration; restart after changing `.env`. Do not reference a
sibling project's virtual environment or secrets file.

API documentation is available at `http://127.0.0.1:8000/docs`. Automated checks:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_chat.py tests/test_chat_data.py tests/test_chat_lazy.py tests/test_chat_stream.py -q
```

These tests use controlled model replies and database fixtures. They verify
the API and query executor, including model-chosen tool sequencing, validation,
calculations, provenance and failure handling. They do not measure the live
provider's accuracy, latency or availability.

For live acceptance checks, use the browser or `/docs` with the configured
provider and current local database:

| Question | Evidence to inspect |
|---|---|
| “Which two specialisations have the highest gender pay gap?” | Descending headline pay-gap query, names/cohort, fractions displayed as percentages |
| “What is the difference between them?” | Follow-up history resolves the records, fresh queries and calculation give percentage points |
| “Which occupations have the lowest risk for legs?” | Legs and feet, complete coverage, ascending score, rounded exposure explanation |
| “Which SA4 regions have the most registered nurses at the latest date?” | Occupation resolution, latest available reference date, regional employment ranking |
| “Which occupations have the highest AI augmentation exposure?” | AI augmentation field sorted across occupations, clear unit and interpretation |
| “For those occupations, compare their weekly earnings.” | Returned occupation IDs connect to profile records; published medians retain their units |
| “What datasets are available, and where do they come from?” | Catalog/source queries with actual available sources |

Check `tools_used`, `data_queries` and `sources` in the response alongside the
answer. Use empty/null values and ambiguous requests as additional checks.
An `answered` status means the model produced a response; it is not proof of
statistical correctness. Compare numeric results with the underlying database
before signing off the feature.

### Local verification on 25 September 2026

- 48 focused chatbot/query/occupation-demand tests passed; the Vue/TypeScript
  production build passed.
- Real NVIDIA calls through the frontend proxy returned the top two gender
  pay-gap specialisations and a tool-calculated 7.6 percentage-point difference.
- A global legs-and-feet ranking worked both without a selection and with an
  unrelated occupation selected. Final display used whole-number indices and
  the mandatory provenance note.
- A follow-up comparing the ranked jobs' weekly earnings caused fresh
  body-region and occupation-profile queries. The returned earnings matched an
  independent read-only database query.
- Successful end-to-end smoke requests took about 42–72 seconds. An earlier
  provider request timed out; latency/availability are not guaranteed.
- The full existing ETL test suite could not pass in this checkout because
  original BOHD, occupation-profile, WCIFR and mobility workbooks were absent.
  No ETL, database schema, database records or Sam's mapping were changed.

These checks validate representative paths, not every possible model-generated
query or answer. Further user-question evaluation is still appropriate.

### Lazy-access and streaming follow-up

- 68 focused backend tests passed, including selected-ID greetings with a DB
  object that raises on any access, streamed tool-argument assembly, partial
  output rejection, timeout classification, bounded retries and SSE contracts.
- 10 frontend stream-parser tests and the Vue/TypeScript production build passed.
  Run frontend checks with `node --test src/api/__tests__/chatStream.test.mjs`.
- A minimal real NVIDIA greeting without tools/data returned first text in
  about 4.1 seconds and finished in 4.7 seconds. This was one control sample,
  not an availability guarantee.
- A real greeting through the frontend SSE proxy showed progress within 0.2
  seconds, timed out on its first model attempt, then succeeded on one retry
  in about 10 more seconds (about 71 seconds total). `tools_used`, `data_queries`
  and `sources` were empty despite an occupation being selected.
- A real legs-and-feet query timed out on both first-round model attempts
  before any database tool was called. It returned explicit `model_timeout`
  / `understanding` metadata, not a claim that the database was loading.
- The same query executed directly through the read-only data tool returned
  three occupations in about 1.3 seconds, including initial schema reflection.
  The JSON compatibility endpoint also experienced first-round provider timeouts;
  the observed issue was not unique to the new SSE transport.

Therefore the local eager-query overhead and misleading loading indicator are
fixed, and failures are observable/bounded. External NVIDIA inference was still
intermittently unavailable during verification; these code changes do not
establish that provider latency or uptime is resolved.
