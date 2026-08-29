"""Minimal stdio MCP server exposing a per-condition cache-isolation sentinel."""

import json
import sys


def _reply(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": code, "message": message}}


def main():
    if len(sys.argv) != 2:
        raise SystemExit("expected one sentinel tool name")
    tool_name = sys.argv[1]
    tool = {
        "name": tool_name,
        "description": "Benchmark cache-isolation sentinel. Do not call this tool.",
        "inputSchema": {"type": "object", "properties": {}},
    }
    for line in sys.stdin:
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}
        if method == "initialize":
            response = _reply(request_id, {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "benchmark-isolation", "version": "1.0"},
            })
        elif method == "tools/list":
            response = _reply(request_id, {"tools": [tool]})
        elif method == "tools/call":
            response = _reply(request_id, {
                "content": [{"type": "text", "text": "sentinel-disabled"}],
                "isError": True,
            })
        elif method and method.startswith("notifications/"):
            continue
        else:
            response = _error(request_id, -32601, f"unsupported method: {method}")
        sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
