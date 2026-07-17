#!/usr/bin/env python3
"""Minimal MCP stdio client for socrata-mcp-server.

Usage:
  mcp_call.py tools/list
  mcp_call.py tools/call <tool_name> '<json_args>'
"""
import json
import os
import subprocess
import sys
import threading

SERVER_JS = os.environ.get(
    "SOCRATA_SERVER_JS",
    os.path.expanduser(
        "~/projects/civic-ai-tools/.mcp-servers/socrata-mcp-server/dist/index.js"
    ),
)
SERVER = ["node", SERVER_JS, "--stdio"]
ENV = {
    "DEFAULT_DOMAIN": "data.cityofnewyork.us",
    "DATA_PORTAL_URL": "https://data.cityofnewyork.us",
    "CACHE_ENABLED": "true",
    "LOG_LEVEL": "error",
    "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    "HOME": os.environ.get("HOME", ""),
}
if os.environ.get("SOCRATA_APP_TOKEN"):
    ENV["SOCRATA_APP_TOKEN"] = os.environ["SOCRATA_APP_TOKEN"]


def rpc(id_, method, params=None):
    msg = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg) + "\n"


def main():
    method = sys.argv[1]
    if method == "tools/list":
        final = rpc(2, "tools/list")
    elif method == "tools/call":
        tool = sys.argv[2]
        args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        final = rpc(2, "tools/call", {"name": tool, "arguments": args})
    else:
        sys.exit(f"unknown method {method}")

    proc = subprocess.Popen(
        SERVER, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, env=ENV,
    )
    timer = threading.Timer(90, proc.kill)
    timer.start()
    try:
        proc.stdin.write(rpc(1, "initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "claude-code-driver", "version": "1.0"},
        }))
        proc.stdin.flush()
        got_init = False
        for line in proc.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("id") == 1 and not got_init:
                got_init = True
                proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
                proc.stdin.write(final)
                proc.stdin.flush()
            elif obj.get("id") == 2:
                print(json.dumps(obj, indent=2))
                return
        print("Server closed stdout without answering. stderr:", proc.stderr.read()[-2000:], file=sys.stderr)
        sys.exit(1)
    finally:
        timer.cancel()
        proc.kill()


if __name__ == "__main__":
    main()
