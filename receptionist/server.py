"""HTTP endpoints for a voice platform. Standard library only.

    GET  /health               liveness check, no auth
    POST /tools/availability   open arrival windows
    POST /tools/book           book a window
    POST /tools/create-lead    save a lead for follow up
    POST /voice/events         call events, answered by the state machine

When TOOL_SHARED_SECRET is set, every POST must send it in the
X-Tool-Secret header.

Run with: python -m receptionist.server
"""

from __future__ import annotations

import hmac
import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Mapping, Optional, Tuple

from .config import BusinessConfig, RuntimeConfig
from .flow import Receptionist, UnknownCall
from .providers import CallRunner, ProviderError, VoiceProvider, get_provider
from .tools import ToolError, ToolService

MAX_BODY_BYTES = 64 * 1024

# Request fields accepted by each tool: name -> (python argument, required).
_TOOL_FIELDS = {
    "/tools/availability": (
        "availability",
        {"job_type": ("job_type", True), "zip": ("zip_code", True),
         "limit": ("limit", False), "after": ("after", False)},
    ),
    "/tools/book": (
        "book",
        {"slot_id": ("slot_id", True), "job_type": ("job_type", True),
         "name": ("name", True), "phone": ("phone", True), "zip": ("zip_code", True),
         "description": ("description", False),
         "idempotency_key": ("idempotency_key", False)},
    ),
    "/tools/create-lead": (
        "create_lead",
        {"reason": ("reason", True), "job_type": ("job_type", False),
         "description": ("description", False), "name": ("name", False),
         "phone": ("phone", False), "zip": ("zip_code", False),
         "urgency": ("urgency", False), "call_id": ("call_id", False)},
    ),
}


class App:
    """Routing and auth, kept free of sockets so it is easy to test."""

    def __init__(
        self,
        business: Optional[BusinessConfig] = None,
        runtime: Optional[RuntimeConfig] = None,
        clock: Optional[Callable[[], datetime]] = None,
        provider: Optional[VoiceProvider] = None,
    ):
        self.business = business or BusinessConfig()
        self.runtime = runtime or RuntimeConfig()
        clock = clock or datetime.now
        self.tools = ToolService(self.business, clock)
        self.receptionist = Receptionist(self.business, self.tools, clock)
        self.provider = provider or get_provider(self.runtime)
        self.runner = CallRunner(self.receptionist, self.provider)

    def handle(
        self, method: str, path: str, headers: Mapping[str, str], body: bytes
    ) -> Tuple[int, dict]:
        path = path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/health":
            if method != "GET":
                return 405, {"error": "method_not_allowed"}
            return 200, {"status": "ok", "voice_provider": self.provider.name}
        if path not in _TOOL_FIELDS and path != "/voice/events":
            return 404, {"error": "not_found"}
        if method != "POST":
            return 405, {"error": "method_not_allowed"}
        if not self._authorized(headers):
            return 401, {"error": "unauthorized"}
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return 400, {"error": "invalid_json"}
        if not isinstance(payload, dict):
            return 400, {"error": "invalid_json", "message": "body must be a JSON object"}
        if path == "/voice/events":
            return self._voice_event(payload)
        return self._tool(path, payload)

    def _authorized(self, headers: Mapping[str, str]) -> bool:
        secret = self.runtime.tool_shared_secret
        if not secret:
            return True
        lowered = {k.lower(): v for k, v in headers.items()}
        supplied = lowered.get("x-tool-secret", "")
        return hmac.compare_digest(supplied.encode("utf-8"), secret.encode("utf-8"))

    def _tool(self, path: str, payload: dict) -> Tuple[int, dict]:
        method_name, fields = _TOOL_FIELDS[path]
        unknown = sorted(set(payload) - set(fields))
        if unknown:
            return 400, {"error": "unknown_field", "message": ", ".join(unknown)}
        missing = sorted(k for k, (_, required) in fields.items() if required and k not in payload)
        if missing:
            return 400, {"error": "missing_field", "message": ", ".join(missing)}
        args = {fields[k][0]: v for k, v in payload.items()}
        try:
            return 200, getattr(self.tools, method_name)(**args)
        except ToolError as exc:
            return exc.status, exc.to_dict()

    def _voice_event(self, payload: dict) -> Tuple[int, dict]:
        try:
            turn = self.runner.dispatch(payload)
        except ProviderError as exc:
            return 400, {"error": "invalid_event", "message": str(exc)}
        except UnknownCall:
            return 404, {"error": "unknown_call"}
        if turn is None:
            return 200, {"status": "ended"}
        return 200, turn.to_dict()


def make_server(app: App, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _respond(self) -> None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY_BYTES:
                status, payload = 413, {"error": "body_too_large"}
            else:
                body = self.rfile.read(length) if length else b""
                status, payload = app.handle(self.command, self.path, dict(self.headers), body)
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = _respond
        do_POST = _respond

        def log_message(self, format: str, *args) -> None:  # keep test output quiet
            return

    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    runtime = RuntimeConfig.from_env()
    app = App(BusinessConfig.from_env(), runtime)
    server = make_server(app, runtime.host, runtime.port)
    print(f"listening on http://{runtime.host}:{server.server_address[1]}")
    print(f"voice provider: {app.provider.name}")
    if not runtime.tool_shared_secret:
        print("warning: TOOL_SHARED_SECRET is not set, endpoints are open")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
