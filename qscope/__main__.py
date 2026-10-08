"""Command-line entry point: ``python -m qscope``.

Serves the QScope API and, when it has been built, the compiled interface at the
same address — so ``python -m qscope`` is the whole application.

    python -m qscope                     # http://127.0.0.1:8000
    python -m qscope --port 9000         # a different port
    python -m qscope --host 0.0.0.0      # reachable from the local network

Environment overrides: ``QSCOPE_HOST``, ``QSCOPE_PORT``, ``QSCOPE_RELOAD``,
``QSCOPE_DB`` (history database) and ``QSCOPE_REPORTS`` (export directory).
"""

from __future__ import annotations

import argparse
import os
import sys

from qscope import __version__


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qscope", description="Run the QScope research environment.")
    parser.add_argument("--host", default=os.environ.get("QSCOPE_HOST", "127.0.0.1"), help="bind address")
    parser.add_argument("--port", type=int, default=int(os.environ.get("QSCOPE_PORT", "8000")), help="bind port")
    parser.add_argument(
        "--reload", action="store_true", default=_env_flag("QSCOPE_RELOAD"), help="reload on source changes"
    )
    parser.add_argument("--version", action="version", version=f"QScope {__version__}")
    parser.add_argument(
        "--info",
        action="store_true",
        help="print the environment and exit instead of serving",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.info:
        import platform

        import numpy as np

        from qscope.experiments import DEFAULT_DB
        from qscope.simulator import backend_catalog, memory_budget_bytes

        print(f"QScope {__version__}")
        print(f"  python      {sys.version.split()[0]} on {platform.platform()}")
        print(f"  numpy       {np.__version__}")
        print(f"  history db  {DEFAULT_DB}")
        print(f"  memory cap  {memory_budget_bytes() / 1e6:.0f} MB (QSCOPE_MEMORY_MB)")
        print("  engines     " + ", ".join(b["key"] for b in backend_catalog()))
        print(f"  llm         {'configured' if os.environ.get('QSCOPE_LLM_BASE_URL') else 'not configured (offline)'}")
        return 0

    import uvicorn

    from qscope.api import app as application

    target = "qscope.api.app:app" if args.reload else application
    banner = f"QScope {__version__} — http://{args.host}:{args.port}"
    print(banner)
    print(f"  API docs    http://{args.host}:{args.port}/api/docs")
    print(f"  interface   http://{args.host}:{args.port}/")
    uvicorn.run(target, host=args.host, port=args.port, reload=args.reload, log_level="info")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
