# Chat protocol and budget verification — 2026-09-27

## What was tested

The user explicitly approved sending the project system prompt, tool definitions,
and public field catalog to the configured NVIDIA endpoint. The effective model
was `deepseek-ai/deepseek-v4.1-flash`; model choice and real `.env` values were not
changed. No production PostgreSQL data, chat history, or actual RAG documents
were sent in these probes.

`scripts/probe_tool_protocol.py` tests model response shape without executing DB
tools. `scripts/probe_chat_workflow.py` uses the real agent loop, query validators,
SQL query engine and calculation tool against an isolated **in-memory synthetic
SQLite database**. Fixture numbers and job names are not real workforce evidence.
The fixture engine is disposed after each run. Reports omit keys, full prompts,
tool arguments and private reasoning.

## Observed live results

| Test | Result | Elapsed |
|---|---|---:|
| Project catalog: retail mobility, native streaming first round | Structured `query_data`; no DSML in content | 44.154s |
| Project catalog: teacher requirements, native streaming first round | Structured `query_data` and `describe_data`; no DSML in content | 32.507s |
| Full loop: retail mobility, auto protocol, synthetic SQL | Native format failed; JSON recovery queried and sorted destinations, then answered | 78.084s |
| Full loop: highest weekly earnings comparison, auto protocol, synthetic SQL | Native format failed; JSON recovery queried and produced a completed answer | 31.281s |
| Full loop: same earnings comparison, direct JSON protocol, synthetic SQL | Two model rounds, one query with backend `difference` calculation; completed | 54.507s |

For the last test, the calculation tool returned **400 AUD per week** from
synthetic values 1600 and 1200. The output retained the synthetic-data disclaimer.
For retail, the fixture produced 17 and 12 recorded movements, sorted correctly.
These tests verify actual tool execution, not just a model saying it used a tool.

The slower direct-JSON sample demonstrates why a reduced call count must not be
reported as guaranteed lower wall-clock latency. Provider queueing and generation
remain variable. The ten-minute learned compatibility hint avoids an extra native
format attempt after successful recovery, but its benefit is measured in avoided
attempts, not a promised number of seconds saved.

## Local regression results

- 166 focused backend tests passed.
- 17 frontend stream/presentation tests passed.
- Frontend type checking and production build passed.
- `git diff --check` passed (Windows line-ending warnings only).

Coverage includes native continuation privacy, protocol recovery and TTL hints,
JSON tool validation, cancellation, analysis-to-summary transition (including a
closed/stalled transport), a shared normal/extended deadline, signed receipt
expiry/tampering, partial history, collapsed evidence, and explicit longer retries.

## Current limits

- This is not a production-data accuracy audit or a sustained availability test.
- Teacher testing established first-round tool format only, not a complete
  qualification/advice answer.
- RAG retrieval itself was excluded from live tests to prevent unapproved document
  transmission; existing offline tests cover its integration.
- A longer retry is a new analysis, not server-side job resumption.
- Restart the backend and refresh the frontend to load the changes. Startup prints
  the effective model, protocol and total/summary budget. No Git submission was made.

For API fields and configuration see [CHAT_EARLY_RESULTS.md](CHAT_EARLY_RESULTS.md).
