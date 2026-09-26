# Chat latency investigation and local optimisation

Date: 26 September 2026 (Australia/Sydney).

## Findings from live requests

The existing model and endpoint were preserved: `openai/gpt-oss-20b` through
NVIDIA's `integrate.api.nvidia.com`. No model switch, database write, ETL change,
or change to Sam's body-region mapping was made.

A single-round streaming benchmark used synthetic questions, temperature 0.2,
top_p 1, max_tokens 3072, no automatic retries, and a 45-second application
deadline per request. The tool definitions were sent for the application cases,
but **no tool was executed and no database was accessed**. Payloads were frozen
at benchmark startup, before the composition changes.

| Case | Effort omitted (provider default) | Explicit low effort |
|---|---|---|
| Minimal request: reply only OK | Deadline reached, no content event | Deadline reached, no content event |
| Greeting with full application prompt/tools | Deadline reached, no content event | Deadline reached, no content event |
| First-round legs/feet exposure ranking plan | Deadline reached, no content event | Deadline reached, no content event |

Six completed attempts: **0/6 completed within the benchmark deadline**. The
planned remaining repetitions were stopped to avoid continuing unproductive
requests. Each variant therefore has only one completed sample per case, not
three. No successful median or p95 can be inferred from these observations;
45 seconds is a cutoff, not the model's measured successful response time.

The raw, metadata-only results are local and ignored by Git:
`data/benchmarks/chat-single-round-baseline-20260926.json`.

Additional controls:

- An unauthenticated GET to NVIDIA's model-list endpoint returned HTTP 200 in
  approximately 0.63 seconds. This confirms that endpoint was reachable, **not**
  that inference was healthy or that the API key was accepted for inference.
- A direct non-streaming HTTP request with a minimal synthetic question, low
  effort and max_tokens 64 reached a read timeout after approximately 20.47
  seconds without response headers. Slow inference is not isolated to the
  application's SSE parser or database code.
- After the composition change, a single comparison-planning request also
  reached its 30-second deadline without a content event. Its separate report
  is `data/benchmarks/chat-composed-query-20260926.json`. Because this is a
  different prompt and cutoff, it is not a like-for-like latency comparison.

These are observations from a small time window, not a production reliability
estimate. They locate the waiting in the inference request path, but cannot
separate provider queueing, inference execution, account routing or network
issues. No end-to-end latency improvement is claimed while the provider is not
returning usable responses. Low reasoning effort was **not** enabled by default.

## Local changes to reduce avoidable model rounds

`query_data` now accepts an optional `calculations` list with up to five
operations referencing zero-based rows and fields in that query's own result.
The backend executes SQL and arithmetic together and returns both as one tool
result. This is generic composition, not keyword-specific answers.

- Previous comparison path: model chooses query; model chooses calculation;
  model writes answer (three model calls).
- Available composed path: model chooses query plus calculation; model writes
  answer (two model calls).

The model still chooses the path. Deterministic tests verify two-call execution
and equivalent checked arithmetic; they do not prove that every live model
request will choose composition. Standalone `calculate` remains available for
cross-query or already-returned results. Questions requiring additional evidence
can legitimately take more rounds. Limits and read-only protections were not
relaxed, and the existing iteration limit was not reduced just to fail sooner.

The prompt now asks the model to finish once it has sufficient evidence, avoid
re-querying successful results just to confirm them, and select only required
fields. Tool schemas are inlined without display titles. The optional
calculation schema adds input size, trading a small schema cost for the ability
to remove an entire later model request.

## Observability and optional configuration

- New `first_model_event` timing separates initial provider text/tool/reasoning
  activity from the first visible answer text. Only arrival time and event kind
  are logged; reasoning content is not saved or exposed.
- `NVIDIA_CHAT_REASONING_EFFORT=default` omits the provider parameter. Supported
  opt-in values are `low`, `medium`, and `high`. Unsupported/blank values are
  omitted. Do not enable lower effort without measuring task accuracy as well
  as latency. No automatic model downgrade or alternate-provider call occurs.
- Existing request budgets, streaming, cancellation and bounded retries remain.

## Reproduce when inference is available

Run from `backend` with your activated Python environment. Point `--env-file`
at your existing local environment file; never paste a key into the command.

```powershell
python scripts/benchmark_chat_latency.py --env-file .env --repeats 3 --efforts default low --timeout 45 --output data/benchmarks/single-round-new-run.json
python scripts/benchmark_chat_latency.py --env-file .env --cases comparison --efforts default low --repeats 3 --timeout 45 --output data/benchmarks/comparison-new-run.json
```

Use a new output filename each time. The script rejects overwrites, allows at
most 24 requests per run, alternates effort order between repetitions, makes
no retries, and stops on authentication/rate-limit responses or six consecutive
failures. The latter limit is configurable. It stores only request-shape hashes,
latencies, finish reasons, tool names and counts, never answers, keys or reasoning.
The comparison case reports whether the model attached calculations, but does
not execute them. Protocol success alone does not establish answer accuracy.

For meaningful evaluation, repeat the same case/configuration in multiple time
windows and measure successful latency, timeout rate, selected tools, argument
validity, end-to-end model-call count and numerical correctness. Compare failures
separately rather than treating timeout durations as successful response times.

Offline tests require only a placeholder database URL for imports; all database
fixtures use isolated SQLite, and model responses are mocked:

```powershell
# Use a separate test terminal, not the terminal used to start the real server.
$env:DATABASE_URL = 'sqlite://'
python -m pytest tests/test_chat.py tests/test_chat_data.py tests/test_chat_lazy.py tests/test_chat_stream.py tests/test_chat_composition.py tests/test_chat_latency_benchmark.py tests/test_occupation_demand_search.py -q
```

All 89 focused chatbot/query/streaming/legacy-demand tests passed in the local
regression run. This is not a claim that the entire ETL suite or live model
answer quality was verified.

## Follow-up: transport compatibility fix (26 September 2026)

The configured model was subsequently changed by the user to
`deepseek-ai/deepseek-v4.1-flash`. The transport fix does not change that model,
the environment file, prompts, database, RAG index, or request budgets.

The installed `openai==3.13.0` uses `httpx2`, whereas the application caught
only `httpx` stream transport exceptions. These exception classes are distinct.
A real `httpx2.ReadTimeout` therefore fell through to the generic handler and
was incorrectly reported as `incomplete_stream` with “response was interrupted”.

Changes:

- Normalize both HTTPX and HTTPX2 stream timeouts/connections into SDK exceptions.
- Handle the SDK's base `APIError` (including error events inside HTTP-200 SSE)
  explicitly as `model_stream_error`; do not disclose raw provider messages.
- Keep the existing single bounded retry for transient errors before output.
  Text, tool fragments, and hidden reasoning all count as consumed output and
  prevent automatic replay. Reasoning text is neither logged nor displayed.
- Declare the already-installed `httpx2==2.12.0` dependency explicitly.

Verification: 110 focused offline tests passed, including 21 new transport tests.
They cover both transport families, bounded retries, partial-output failures,
cancellation/deadlines, and actual SDK parsing of simulated SSE error events.

A single live greeting probe used the actual environment file, no database or
RAG, a process-local 15-second model timeout, and zero retries. It still timed
out after approximately 16.35 seconds, but now correctly returned
`model_timeout`, stage `understanding`, with `APITimeoutError` in timing metadata.
Those diagnostic settings were not saved. This confirms error classification,
not restored provider availability or successful DeepSeek tool execution.

## Documentation consulted

OpenAI Docs guided reducing sequential requests rather than bypassing verified
calculations: [Latency optimisation](https://developers.openai.com/api/docs/guides/latency-optimization).
The exact NVIDIA model's API documents `reasoning_effort` and its default:
[NVIDIA gpt-oss-20b API](https://docs.api.nvidia.com/nim/reference/openai-gpt-oss-20b-infer).
Support in documentation does not guarantee improved measured latency.
