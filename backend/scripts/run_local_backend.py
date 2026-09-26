"""Windows local launcher: one project, one interpreter, one explicit .env.

Local .env values deliberately override stale shell settings. Production keeps
using its normal ASGI entry point and environment-variable precedence.
"""

import argparse
import os
from pathlib import Path
import sys

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-reload", action="store_true")
    args = parser.parse_args()
    expected_python = ROOT / ".venv" / "Scripts" / "python.exe"
    if Path(sys.executable).resolve() != expected_python.resolve():
        parser.error("Use backend/start_backend.cmd to select backend/.venv.")
    if not (ROOT / ".env").is_file():
        parser.error("Missing backend/.env; configure it before starting.")
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535.")
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    load_dotenv(ROOT / ".env", override=True)
    # Display paths only; never print credentials or connection strings.
    print(f"Python: {sys.executable}", flush=True)
    print(f"Environment file: {ROOT / '.env'}", flush=True)
    print(f"Chat model: {os.getenv('NVIDIA_CHAT_MODEL', 'deepseek-ai/deepseek-v4.1-flash')}", flush=True)
    print(f"Tool protocol: {os.getenv('CHAT_TOOL_PROTOCOL', 'auto')}", flush=True)
    from app.services.chat_budget import ChatBudget
    budget = ChatBudget.configured()
    print(f"Chat budget: {budget.total}s total, {budget.reserve}s reserved for summary", flush=True)
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port,
                reload=not args.no_reload, reload_dirs=[str(ROOT)] if not args.no_reload else None)


if __name__ == "__main__":
    main()
