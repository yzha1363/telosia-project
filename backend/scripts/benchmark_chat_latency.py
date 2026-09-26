"""Opt-in, single-round NVIDIA benchmark. Never executes tools or queries a DB.

Only synthetic questions are sent. Reports contain timing/shape metadata, not
keys, answers, tool arguments, or reasoning text. No automatic retries.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from statistics import median
import sys
from threading import Event, Timer
from time import monotonic
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def build_cases():
    from app.services.chat_data import prompt_catalog
    from app.services.chat_tools import get_chat_tools
    from app.services.nvidia_chat import SYSTEM_PROMPT

    context = {"selected_occupation_id": None, "page_context": None,
               "data_catalog": prompt_catalog()}
    system = SYSTEM_PROMPT + "\nCONTEXT (IDs and schema hints, not data):\n" + json.dumps(
        context, ensure_ascii=False, separators=(",", ":"), default=str,
    )
    tools = get_chat_tools()
    return {
        "minimal": {"messages": [{"role": "user", "content": "Reply only with OK."}]},
        "greeting": {"messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": "Hi!"}],
                     "tools": tools, "tool_choice": "auto"},
        "ranking": {"messages": [{"role": "system", "content": system}, {"role": "user",
                    "content": "Which three occupations have the lowest recorded work-demand exposure for legs and feet?"}],
                    "tools": tools, "tool_choice": "auto"},
        "comparison": {"messages": [{"role": "system", "content": system}, {"role": "user",
                       "content": "Find the two occupation profiles with the highest published median weekly earnings and calculate the absolute difference between those two figures."}],
                       "tools": tools, "tool_choice": "auto"},
    }


def measure(client, payload, timeout):
    """Measure first evidence/output and full round, without retaining content."""
    started = monotonic()
    expired = Event()
    def expire():
        expired.set()
        client.close()
    timer = Timer(timeout, expire)
    timer.daemon = True
    result = {"first_event_ms": None, "first_text_ms": None, "first_tool_ms": None,
              "finish_reason": None, "tool_names": [], "status": "error",
              "attached_calculation_count": 0}
    calls = {}
    stream = None
    text_seen = False
    timer.start()
    try:
        stream = client.chat.completions.create(**payload, stream=True, timeout=timeout)
        for chunk in stream:
            elapsed = round((monotonic() - started) * 1000)
            if expired.is_set():
                raise TimeoutError()
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            fragments = getattr(delta, "tool_calls", None) or []
            content = getattr(delta, "content", None)
            reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
            if (content or reasoning or fragments) and result["first_event_ms"] is None:
                result["first_event_ms"] = elapsed
            if content:
                text_seen = True
                if result["first_text_ms"] is None:
                    result["first_text_ms"] = elapsed
            if fragments and result["first_tool_ms"] is None:
                result["first_tool_ms"] = elapsed
            for fragment in fragments:
                item = calls.setdefault(fragment.index, {"name": "", "arguments": ""})
                if fragment.function:
                    item["name"] += fragment.function.name or ""
                    item["arguments"] += fragment.function.arguments or ""
            if choice.finish_reason:
                result["finish_reason"] = choice.finish_reason
        result["tool_names"] = [item["name"] for item in calls.values()]
        valid_calls = True
        for item in calls.values():
            try:
                arguments = json.loads(item["arguments"])
                valid_calls = valid_calls and isinstance(arguments, dict)
                if item["name"] == "query_data" and isinstance(arguments, dict):
                    calculations = arguments.get("calculations", [])
                    if isinstance(calculations, list):
                        result["attached_calculation_count"] += len(calculations)
            except (ValueError, TypeError):
                valid_calls = False
        result["valid_tool_json"] = valid_calls
        result["status"] = "ok" if (
            result["finish_reason"] in {"stop", "tool_calls"}
            and (text_seen or bool(calls)) and valid_calls
        ) else "incomplete"
    except Exception as exc:
        # Do not store str(exc): provider error bodies can contain request data.
        result["error_type"] = "DeadlineExceeded" if expired.is_set() else type(exc).__name__
        result["http_status"] = getattr(exc, "status_code", None)
    finally:
        timer.cancel()
        result["total_ms"] = round((monotonic() - started) * 1000)
        if stream:
            stream.close()
        client.close()
    return result


def summarise(samples):
    groups = defaultdict(list)
    for row in samples:
        groups[(row["case"], row["effort"])].append(row)
    summary = []
    for (case, effort), rows in groups.items():
        passed = [r for r in rows if r["status"] == "ok"]
        duration = [r["total_ms"] for r in passed]
        summary.append({"case": case, "effort": effort, "attempts": len(rows),
                        "successes": len(passed), "failures": len(rows) - len(passed),
                        "successful_median_ms": median(duration) if duration else None,
                        "successful_min_ms": min(duration) if duration else None,
                        "successful_max_ms": max(duration) if duration else None,
                        "direct_query_calls": sum("query_data" in r["tool_names"] for r in rows),
                        "attached_calculation_calls": sum(r.get("attached_calculation_count", 0) > 0 for r in rows)})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--repeats", type=int, default=3, choices=range(1, 6))
    parser.add_argument("--efforts", nargs="+", choices=["default", "low", "medium", "high"], default=["default", "low"])
    parser.add_argument("--cases", nargs="+", choices=["minimal", "greeting", "ranking", "comparison"], default=["minimal", "greeting", "ranking"])
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument("--max-consecutive-failures", type=int, default=6, choices=range(1, 25))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 5 <= args.timeout <= 120:
        parser.error("timeout must be between 5 and 120 seconds")
    if len(args.cases) * len(args.efforts) * args.repeats > 24:
        parser.error("At most 24 requests per run; reduce cases, efforts, or repeats")
    if args.output.exists():
        parser.error("Output already exists; choose a new file to preserve earlier measurements")
    if args.env_file:
        if not args.env_file.is_file():
            parser.error("The supplied env file does not exist")
        load_dotenv(args.env_file, override=False)
    else:
        load_dotenv(ROOT / ".env", override=False)
    from app.services.nvidia_chat import _create_client, DEFAULT_MODEL, DEFAULT_API_BASE
    model = os.getenv("NVIDIA_CHAT_MODEL", DEFAULT_MODEL)
    # Freeze payloads before the run so edits during the benchmark cannot mix versions.
    cases = build_cases()
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "model": model,
              "endpoint_host": urlparse(os.getenv("NVIDIA_API_BASE", DEFAULT_API_BASE)).hostname,
              "timeout_seconds": args.timeout, "max_tokens": 3072, "retries": 0,
              "planned_requests": len(args.cases) * len(args.efforts) * args.repeats,
              "run_state": "running",
              "note": "Small sequential sample, not a production SLA. No tools executed. Success is protocol-level, not clinical/data-answer accuracy.",
              "samples": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    consecutive_failures = 0
    def save():
        report["summary"] = summarise(report["samples"])
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for repeat in range(args.repeats):
        for case in args.cases:
            # Alternate effort order to reduce systematic warm-up/time-of-day bias.
            efforts = args.efforts if repeat % 2 == 0 else list(reversed(args.efforts))
            for effort in efforts:
                payload = {"model": model, "temperature": 0.2, "top_p": 1,
                           "max_tokens": 3072, **cases[case]}
                fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
                if effort != "default":
                    payload["reasoning_effort"] = effort
                try:
                    result = measure(_create_client(), payload, args.timeout)
                except KeyboardInterrupt:
                    report["run_state"] = "interrupted"
                    save()
                    return 130
                result.update(case=case, effort=effort, repeat=repeat + 1, payload_sha256=fingerprint)
                report["samples"].append(result)
                consecutive_failures = 0 if result["status"] == "ok" else consecutive_failures + 1
                save()
                print(json.dumps(result), flush=True)
                if result.get("http_status") in {401, 403, 429}:
                    report["run_state"] = "access_or_rate_limit"
                    save()
                    print("Stopped: credentials/access/rate limit must be resolved before more requests.", flush=True)
                    return 1
                if consecutive_failures >= args.max_consecutive_failures:
                    report["run_state"] = "consecutive_failures"
                    save()
                    print("Stopped after consecutive failures; skipped requests are not counted as failures.", flush=True)
                    return 1
    report["run_state"] = "completed"
    save()
    print(json.dumps({"summary": report["summary"]}), flush=True)
    return 0 if all(row["status"] == "ok" for row in report["samples"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
