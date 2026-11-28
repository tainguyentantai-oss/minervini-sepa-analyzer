#!/usr/bin/env python3
"""
Standalone Local Stdio MCP Server for Minervini SEPA Analyzer
Compatible with Claude Desktop, Cursor, and Antigravity IDE.

Captures real stdout for pure JSON-RPC 2.0 framing and redirects all internal
module stdout logs to stderr so protocol framing is never corrupted.
"""
import json
import sys
from pathlib import Path

_REAL_STDOUT = sys.stdout
sys.stdout = sys.stderr

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from engine.mcp_core import handle_mcp_jsonrpc  # noqa: E402


def main():
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception as e:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"},
            }
            _REAL_STDOUT.write(json.dumps(err_resp, ensure_ascii=False) + "\n")
            _REAL_STDOUT.flush()
            continue

        resp = handle_mcp_jsonrpc(payload)
        if resp is not None:
            _REAL_STDOUT.write(json.dumps(resp, ensure_ascii=False, allow_nan=False) + "\n")
            _REAL_STDOUT.flush()


if __name__ == "__main__":
    main()
