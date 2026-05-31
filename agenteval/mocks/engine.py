"""A single mock MCP server spoken over Streamable-HTTP.

Ports the dispatch / state / __calls__ logic of the original Node engine to
Python's stdlib http.server (zero extra deps). POST /mcp accepts JSON-RPC and
returns JSON-RPC; GET /mcp and GET / are liveness probes. One MockServer
instance backs one mock.yaml.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .handlers import HandlerContext, load_handlers
from .spec import MockSpec, MockState, apply_mutations, render_value, template_context

PROTOCOL_VERSION = "2024-11-05"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _wrap_content(out: Any) -> dict[str, Any]:
    """Wrap a plain handler return as MCP text content, pass through if shaped."""
    if out is None:
        out = {"ok": True}
    if isinstance(out, dict) and "content" in out:
        return out
    return {"content": [{"type": "text", "text": json.dumps(out, indent=2, default=str)}]}


class MockServer:
    """Owns the state + dispatch for one mock; serves it on a port in a thread."""

    def __init__(self, spec: MockSpec):
        self.spec = spec
        self.state = MockState(spec.seed)
        self.handlers = load_handlers(spec.handler_path, spec.name)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port: int | None = None

    # ── dispatch ──────────────────────────────────────────────────────────

    def _dispatch_tool(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool not in self.spec.tool_names():
            return {"__error__": (-32601, f"Unknown tool: {tool}")}

        handler = self.handlers.get(tool)
        if handler is not None:
            ctx = HandlerContext(state=self.state, server=self.spec.name, tool=tool)
            out = handler(args, ctx)
        else:
            out = self._declarative(tool, args)

        # Always record the call for tool_called / audit assertions.
        self.state.mutate(
            lambda s: s.setdefault("__calls__", []).append(
                {"at": _now_iso(), "tool": tool, "args": args}
            )
        )
        return _wrap_content(out)

    def _declarative(self, tool: str, args: dict[str, Any]) -> Any:
        rules = self.spec.responses.get(tool)
        if not rules:
            # Generic fallback: acknowledge + echo, like the Node defaultFallback.
            return {"ok": True, "note": f"[{self.spec.name}] mock fallback for {tool}", "args": args}
        for rule in rules:
            if not rule.matches(args):
                continue
            ctx = template_context(args, self.state)
            if rule.mutate:
                apply_mutations(rule.mutate, self.state, ctx)
            if rule.error is not None:
                return {"ok": False, "error": rule.error}
            if rule.result is not None:
                return render_value(rule.result, ctx)
            return {"ok": True}
        return {"ok": False, "error": "no_matching_rule"}

    def handle_rpc(self, body: dict[str, Any]) -> tuple[dict[str, Any] | None, int]:
        rpc_id = body.get("id")
        method = body.get("method")
        params = body.get("params") or {}

        if method == "initialize":
            return (
                {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {"tools": {"listChanged": False}, "logging": {}},
                        "serverInfo": {"name": f"mock-{self.spec.name}", "version": "0.1.0"},
                    },
                },
                200,
            )
        if method == "notifications/initialized":
            return (None, 202)
        if method == "tools/list":
            return ({"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": self.spec.tools}}, 200)
        if method == "ping":
            return ({"jsonrpc": "2.0", "id": rpc_id, "result": {}}, 200)
        if method == "tools/call":
            tool = params.get("name")
            args = params.get("arguments") or {}
            out = self._dispatch_tool(tool, args)
            if "__error__" in out:
                code, message = out["__error__"]
                return ({"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}, 200)
            return ({"jsonrpc": "2.0", "id": rpc_id, "result": out}, 200)

        return (
            {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": f"Method not found: {method}"}},
            200,
        )

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self, port: int = 0) -> int:
        handler_cls = _make_handler(self)
        self._httpd = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self.port

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def reset(self) -> None:
        self.state.reset()

    def snapshot(self) -> dict[str, Any]:
        return self.state.snapshot()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"


def _make_handler(server: MockServer):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # silence default stderr logging
            pass

        def _send_json(self, obj: Any, status: int = 200) -> None:
            payload = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):  # noqa: N802
            if self.path in ("/", "/health"):
                return self._send_json({"ok": True, "name": server.spec.name, "port": server.port})
            if self.path == "/state":
                return self._send_json(server.snapshot())
            if self.path.startswith("/mcp"):
                return self._send_json({"ok": True, "transport": "streamable-http", "name": server.spec.name})
            return self._send_json({"error": "not found"}, 404)

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("content-length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"

            if self.path == "/__reset__":
                server.reset()
                return self._send_json({"ok": True})

            if not self.path.startswith("/mcp"):
                return self._send_json({"error": "not found"}, 404)

            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return self._send_json(
                    {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
                    400,
                )

            try:
                response, status = server.handle_rpc(body)
            except Exception as exc:  # never let a handler crash the server
                return self._send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": body.get("id"),
                        "error": {"code": -32603, "message": f"Internal: {exc}"},
                    },
                    500,
                )

            if response is None:  # JSON-RPC notification: no body, but under
                # HTTP/1.1 keep-alive we must still frame the (empty) response
                # with Content-Length: 0 or the client hangs waiting for a body.
                self.send_response(status)
                self.send_header("content-length", "0")
                self.end_headers()
                return None
            return self._send_json(response, status)

    return Handler
