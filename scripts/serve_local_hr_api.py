#!/usr/bin/env python3
"""Run the LOCAL HR API simulator as its own process (real HTTP, SQLite state).

This is the target of the `http` integration mode ("LOCAL HTTP INTEGRATION"). It is a
local simulator of an HR system -- **not** a real HR system, and not a production
deployment. It binds to 127.0.0.1 by default and holds no employee data: one form record
per evidenced route. Note content is measured and discarded; only its length is kept.

Standard library only (`http.server`, `sqlite3`).

Usage:
    python scripts/serve_local_hr_api.py                      # 127.0.0.1:8100
    python scripts/serve_local_hr_api.py --db /tmp/hr.db --port 8123
    python scripts/serve_local_hr_api.py --port 0             # ephemeral; prints the port

Environment:
    LOCAL_HR_DB_PATH     SQLite file (default: ./local_hr_system.db)
    LOCAL_HR_API_TOKEN   development service credential shared with the adapter
                         (a local default is used when unset; it protects nothing)
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from procmine.integrations.local_hr_api import (  # noqa: E402
    DEFAULT_HOST, DEFAULT_PORT, build_hr_server,
)


def _stop(signum, frame) -> None:
    raise KeyboardInterrupt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db", default=os.environ.get("LOCAL_HR_DB_PATH")
                        or "local_hr_system.db")
    parser.add_argument("--verbose", action="store_true", help="log request lines")
    args = parser.parse_args()

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("refusing to bind a non-loopback address: this is a local simulator",
              file=sys.stderr)
        return 2

    server = build_hr_server(args.db, args.host, args.port, quiet=not args.verbose)
    # Stop cleanly on SIGTERM too, so a supervising test or demo can restart it.
    signal.signal(signal.SIGTERM, _stop)
    host, port = server.server_address[:2]
    # The first stdout line is machine-readable, for callers that asked for port 0.
    print(f"LISTENING http://{host}:{port}", flush=True)
    print(f"LOCAL HR API simulator -- SQLite state in {args.db}", file=sys.stderr)
    print("  GET  /api/hr/health | /api/hr/routes | /api/hr/records/{record_id}",
          file=sys.stderr)
    print("  POST /api/hr/records/{record_id}/notes | /api/hr/records/{record_id}/confirm",
          file=sys.stderr)
    print("  GET  /api/hr/executions/{execution_id}/status", file=sys.stderr)
    print("NOT a real HR system. Local HTTP integration only.", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
