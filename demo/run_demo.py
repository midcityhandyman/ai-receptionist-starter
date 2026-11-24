"""Offline demo: scripted calls through the simulator, then the tool endpoints.

Run from the repository root:

    python demo/run_demo.py
    python demo/run_demo.py --understanding claude

No network access and no API keys are needed by default. The captured
output of the default run is saved in demo/output.txt.

--understanding picks how caller lines are understood: keyword (the
default) plays the rule based scenarios and then the model path
scenarios with recorded replies from a fake client, all offline.
claude plays every scenario against the real model through the
Anthropic SDK, which needs the SDK and credentials and sends the
scripted caller lines to the API.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from receptionist import simulator  # noqa: E402
from receptionist.config import RuntimeConfig  # noqa: E402
from receptionist.server import App  # noqa: E402


def call(app: App, path: str, body: dict, secret: str = "demo-secret") -> None:
    headers = {"X-Tool-Secret": secret} if secret else {}
    status, payload = app.handle("POST", path, headers, json.dumps(body).encode("utf-8"))
    print(f"POST {path}")
    print(f"  request:  {json.dumps(body)}")
    print(f"  response: {status} {json.dumps(payload)}")
    print()


def tool_endpoint_demo() -> None:
    print("=" * simulator.WIDTH)
    print("TOOL ENDPOINTS (the same handlers the HTTP server exposes)")
    print("=" * simulator.WIDTH)
    app = App(
        runtime=RuntimeConfig(tool_shared_secret="demo-secret"),
        clock=lambda: datetime(2030, 1, 7, 10, 15),
    )
    call(app, "/tools/availability", {"job_type": "plumbing", "zip": "00102", "limit": 2})
    booking = {
        "slot_id": "2030-01-08T08:00",
        "job_type": "plumbing",
        "name": "Alex Sample",
        "phone": "555-555-0142",
        "zip": "00102",
        "idempotency_key": "demo-1",
    }
    call(app, "/tools/book", booking)
    print("A second caller tries the same window:")
    call(app, "/tools/book", dict(booking, name="Riley Testcase", idempotency_key="demo-2"))
    call(
        app,
        "/tools/create-lead",
        {"reason": "callback_requested", "job_type": "hvac", "name": "Riley Testcase",
         "phone": "555-555-0155", "zip": "00104", "description": "Thermostat is blank"},
    )
    print("A request without the shared secret:")
    call(app, "/tools/availability", {"job_type": "plumbing", "zip": "00102"}, secret="")
    print("The same availability tool in Vapi's custom tool format")
    print("(built from Vapi's documentation, never run against a Vapi account):")
    call(
        app,
        "/vapi/tools",
        {"message": {"type": "tool-calls", "toolCallList": [
            {"id": "call_demo_1", "type": "function", "function": {
                "name": "check_availability",
                "arguments": {"job_type": "hvac", "zip": "00104", "limit": 1}}}]}},
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Offline demo of the receptionist starter.")
    parser.add_argument(
        "--understanding", choices=(simulator.KEYWORD, simulator.CLAUDE),
        default=simulator.KEYWORD,
        help="keyword (default, offline) or claude (live model, needs the SDK and credentials)",
    )
    mode = parser.parse_args(argv).understanding
    code = simulator.main(["--understanding", mode])
    if mode == simulator.KEYWORD:
        print()
        code = simulator.main(["--understanding", simulator.RECORDED]) or code
    print()
    tool_endpoint_demo()
    return code


if __name__ == "__main__":
    sys.exit(main())
