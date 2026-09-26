# Chat early evidence and failure handling

## Maintainability update

- Removed the unused static knowledge-file read from chat preparation. Selection
  metadata is prepared without file or database access; optional RAG remains a tool.
- Removed the retired keyword intent, occupation ranking and fixed pay-gap answer
  modules and their dedicated tests. Current query-engine tests retain coverage of
  the body-region MAX mapping and incomplete exposure records.
- Unified numeric configuration parsing and the per-call model timeout (10–120
  seconds, default 60) across client defaults and request overrides.
- Extracted provider transport normalization from the orchestration loop and
  shared response construction between completed and failed requests.
- Source details are cached within each request, while every query keeps its own
  provenance. Sources and results are not cached across user requests.
- Assistant Markdown is computed in a child component. Unchanged message rows
  skip rendering during streaming; HTML sanitization remains enabled.

These changes reduce redundant work and maintenance cost. They do not establish
live-provider latency improvements or resolve every malformed tool response.

Validation: 154 existing focused chat tests passed, then the changed budget and
composition suites passed all 24 tests including four added regression cases.
The 17 frontend stream/presentation tests and production build (including type
checking) passed. The full backend suite reported 222 passed, 10 skipped,
1 failed and 32 setup errors: the failures require missing raw ETL workbooks
under `backend/datasets`. No live model or production database test was run.

## Budget and evidence UI update (current behavior)

- Normal requests default to **240 seconds total**, with **60 seconds reserved
  for an evidence-only summary**. An explicit longer retry requests up to **300
  seconds**. The shared `ChatBudget` is used by both the route and model loop.
- `CHAT_TOTAL_TIMEOUT_SECONDS`, `CHAT_SUMMARY_RESERVE_SECONDS`, and
  `CHAT_EXTENDED_TIMEOUT_SECONDS` configure these bounds; the total hard cap is
  300 seconds. Actual `.env` or process values override defaults. Editing only
  `.env.example` does not configure a running server. Startup prints the effective
  model, protocol, and budget, without keys or connection strings.
- At the analysis deadline, a phase timer closes a stalled planning connection.
  A fresh client may then perform one evidence-only summary using the reserve.
  No new tools execute during that summary. Disconnect and total-deadline
  cancellation still stop the request; no retry may extend the hard deadline.
- The initial SSE status advertises `timeout_ms` (total plus 15 seconds of
  transport allowance). The UI respects that limit unless its caller explicitly
  sets a shorter timeout. The route itself stops after total plus five seconds.
- Forced summaries and failures with completed evidence return `status: partial`.
  Ordinary failures with no evidence remain `temporarily_unavailable`. A partial
  summary is not certified as a fully completed answer.
- Evidence is collapsed by default and grouped under readable dataset names.
  Each query retains its own scope, rows, units, notes and sources. Historical
  evidence belongs to its original message, not a global "latest query" widget.
- The UI offers an explicit longer **retry**, not a resumable job. It starts a
  new request and may re-query data; it is never started automatically. Old-job
  retries are hidden after changing the selected occupation.

### Previous-turn state and API additions

Requests accept `extended_analysis: boolean` and `previous_turn_token: string`.
Responses add `turn_token` and the `partial` status. The token is a signed,
one-hour receipt containing only status, request ID and queried dataset names:
no message text, query rows, numeric claims or private reasoning. Invalid/expired
receipts are ignored. Without `CHAT_CONTEXT_SIGNING_KEY`, its signing key is
process-local; configure a shared secret for multi-worker production deployments.
Receipts are continuity metadata, not authentication or authorization credentials.

The frontend includes incomplete turns in history as explicitly incomplete status
summaries, not as verified numeric answers. The backend verifies the receipt and
provides its own UI behavior description to the model. New numeric comparisons
must still query data; this is not a persistent result cache or session memory DB.

Example request after an incomplete answer:

```json
{
  "message": "Why is that evidence still visible?",
  "previous_turn_token": "<turn_token from the preceding response>",
  "history": [],
  "extended_analysis": false
}
```

Protocol repair below is retained. After explicit permission, live tests sent the
project prompt/catalog and ran the production query engine against an isolated
synthetic SQLite fixture. No production PostgreSQL records or RAG documents were
sent. See [the verification report](CHAT_PROTOCOL_VERIFICATION.md) for measured
results and limits; successful samples do not establish production reliability.

## Protocol repair update

The previous marker guard prevented leakage but did not recover the request.
The current implementation adds a provider-independent recovery transport:

- `CHAT_TOOL_PROTOCOL=auto` (default): start with native `tool_calls`. On a
  malformed text-tool protocol, reset provisional text and switch once to a
  JSON action transport if at least 15 seconds remain. The model chooses tool
  names and arguments; existing read-only validators execute them. Verified
  earlier results are preserved. This is not keyword or occupation routing.
- `native`: disable the recovery transport for diagnosis.
- `json`: start directly with the alternative transport. Tools are described
  in the system contract, rather than the provider's native `tools` parameter.

After a recovered JSON request completes successfully, `auto` remembers that
working transport for ten minutes for the same endpoint/model/tool-contract hash.
This bounded process-local cache holds at most 32 compatibility hints, not user
questions or query results. Failure clears the hint; restart or expiry allows a
fresh native attempt. Explicit `native`/`json` settings override the hint.

The alternative transport accepts a complete JSON tool-action envelope or a
normal final answer/clarification. It does not extract tools from prose, execute
DSML, accept unknown tool names, or execute incomplete JSON. It deliberately
does not request provider `response_format=json_object`: a minimal live probe
of the configured service returned an empty body with that parameter.
Action responses are buffered until validated; raw JSON is never streamed to
the UI. Database results still arrive through `data_result` immediately.

Native tool turns now preserve a provider's `reasoning_content` continuation
field in request-local assistant messages. This corrects a missing part of
the DeepSeek thinking/tool continuation contract. It is never sent to the
frontend, placed in response context, logged, persisted, or used as evidence.
The earlier statement that reasoning text was never retained is superseded:
it is now held only for provider continuation within the active request.

### Evidence and remaining validation

The local `.env` used by the live probes selected
`deepseek-ai/deepseek-v4.1-flash`, not the GLM model in `.env.example`.
Synthetic minimal native tool probes succeeded in both non-streaming (~21.6s)
and streaming (~22.4s) modes. A prompt-only JSON action request also succeeded
(~3.1s). These are individual observations, not latency guarantees.
Subsequent synthetic summary probes demonstrated both timeouts and ordinary
text answers rather than JSON; ordinary final text is now explicitly allowed.
Those early minimal tests did not prove full-workflow reliability. Subsequent
authorized project-contract and synthetic SQL workflow tests completed successfully;
their exact scope and timings are recorded in the verification report.

Offline verification: 166 focused backend tests and 17 frontend tests pass, including native
continuation privacy, bounded protocol recovery, model-chosen queries across
datasets, unchanged JSON arguments, plain final answers, and rejection of
unknown/embedded/incomplete action packets. No database/ETL change or Git
submission was made. Real `.env` values were not changed; `.env.example` was
sanitized to contain a placeholder key. Rotate any previously exposed key.

References: [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling),
[DeepSeek thinking/tool continuation](https://api-docs.deepseek.com/guides/thinking_mode/),
[NVIDIA's deployed-model API](https://docs.api.nvidia.com/nim/re/reference/nvidia-deepseek-v4_1-flash-infer).
The DeepSeek direct API documentation describes its continuation requirement;
NVIDIA-hosted behavior was subsequently sampled with project contracts and synthetic
SQL fixtures. It is not a claim that every future question or service request succeeds.

## Scope

This increment changes chat orchestration and display only. It does not change
Sam's body-region MAX mapping, ETL, database schema, stored data, model selection,
credentials, or RAG index. No new dependency or migration is required.

## Request flow

1. The model selects structured tools from the existing catalog.
2. The backend validates arguments and executes read-only queries.
3. A successful query immediately emits an SSE `data_result` event. The UI shows
   up to ten returned rows with units, query scope, dataset notes and provenance.
4. The model can continue analysis or produce its summary. Intermediate evidence
   is explicitly not a final recommendation and may be superseded by later queries.
5. Both JSON and final SSE responses include `data_results`. If the model fails
   after retrieving evidence, status is `partial`, not `answered`; completed evidence
   remains visible. Text resets, stream errors and Stop do not erase evidence.

Body-exposure evidence carries the BOHD beta/US-mapping disclosure and the
non-medical limitation even when the model cannot finish its summary. Fraction
units remain fractions, not silently converted to percentages. Empty results and
NULL values are not zero; limited previews are not whole-dataset statistics.

## Avoiding wasted work

- Boolean-typed filters accept JSON booleans and exact case-insensitive string
  literals `true` / `false` (surrounding whitespace allowed). `yes`, numbers and
  other ambiguous values still fail validation. Text fields are unchanged.
- Within one request, successful identical tool calls reuse their results.
  Repeated identical failed calls terminate the loop with `repeated_tool_error`
  before executing again. Changed arguments can still be tried.
- Text containing known DSML/function-call markers is rejected with
  `tool_protocol_error`, including markers split across streamed chunks.
  Text tags are never executed as tools or accepted as a successful answer.
  This detects a protocol failure; it does not repair provider tool support.

## Performance boundary

Early evidence reduces **time until data is visible**, not the provider's first
tool-call latency. Request-local reuse saves duplicate tool work. The model still
gets a summary/analysis round; this change does not force all requests into one
model call or weaken complex comparisons. Existing total deadlines remain.
No live-provider latency improvement is claimed from offline regression tests.

## Verification and restart

From `backend`, run `start_backend.cmd` after stopping the previous backend.
From `frontend`, run `npm.cmd run dev` and refresh the browser.

Tests cover split protocol markers, strict boolean conversion, repeated failures,
duplicate successful calls, early evidence before the next model call, and retained
results/sources after a simulated model timeout. Frontend stream tests:
`node --test src/api/__tests__/chatStream.test.mjs`.

Try: `If I have issues with my lower back, which jobs have lower recorded exposure?`
Expect a query-evidence table followed by a summary. A provider failure should
leave the table visible with an incomplete-analysis message, not fabricated advice.

Protocol implementation follows the separation of tool calls and message content
described in [OpenAI's function-calling documentation](https://developers.openai.com/api/docs/guides/function-calling).
Compatibility of a particular NVIDIA-hosted model must still be tested separately.
