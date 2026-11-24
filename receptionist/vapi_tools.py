"""Adapter for Vapi custom tools (the "tool-calls" server message).

WRITTEN FROM DOCUMENTATION, NOT TESTED AGAINST A LIVE VAPI ACCOUNT.
Source: https://docs.vapi.ai/tools/custom-tools (request and response
format) and https://docs.vapi.ai/server-url/server-authentication
(sending a secret in a custom header), both read on 2026-11-24. The
unit tests use payloads copied in shape from the examples on those
pages. Nothing here has received a request from Vapi.

In this mode Vapi runs the conversation with its own model and only
calls the three tools. The state machine in flow.py is not involved,
so its guarantees (disclosure, deterministic handoff) do not apply;
those would have to be set up in the Vapi assistant itself.

Request, as documented:

    {"message": {"type": "tool-calls",
                 "toolCallList": [{"id": "...", "type": "function",
                                   "function": {"name": "...",
                                                "arguments": {...}}}],
                 ...}}

Response, as documented: always HTTP 200, one entry per call, each with
either "result" or "error", both flat single line strings:

    {"results": [{"toolCallId": "...", "result": "..."}]}

Function names to configure on the Vapi side, with the same argument
names as the /tools/* endpoints in server.py:

    check_availability   job_type, zip, limit?, after?
    book_appointment     slot_id, job_type, name, phone, zip,
                         description?, idempotency_key?
    create_lead          reason, job_type?, description?, name?, phone?,
                         zip?, urgency?, call_id?

Auth: the docs describe a Bearer Token credential with a custom header
name and the Bearer prefix turned off. Point that at X-Tool-Secret and
the existing TOOL_SHARED_SECRET check in server.py covers this route.
"""

from __future__ import annotations

import json
from typing import Callable, Tuple

VAPI_TOOLS_PATH = "/vapi/tools"

FUNCTIONS = {
    "check_availability": "/tools/availability",
    "book_appointment": "/tools/book",
    "create_lead": "/tools/create-lead",
}

RunTool = Callable[[str, dict], Tuple[int, dict]]


class VapiPayloadError(ValueError):
    """The request is not a tool-calls message in the documented shape."""


def _one_line(value: str) -> str:
    return " ".join(str(value).split())


def handle_tool_calls(payload: dict, run_tool: RunTool) -> dict:
    """Run every call in a tool-calls message and build Vapi's response.

    run_tool takes one of the /tools/* paths and an argument object and
    returns (status, payload), exactly like the HTTP tool endpoints.
    """
    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, dict):
        raise VapiPayloadError("message is required")
    if message.get("type") != "tool-calls":
        raise VapiPayloadError(f"unsupported message type: {message.get('type')!r}")
    calls = message.get("toolCallList")
    if not isinstance(calls, list) or not calls:
        raise VapiPayloadError("message.toolCallList must be a non-empty list")

    results = []
    for call in calls:
        if not isinstance(call, dict) or not isinstance(call.get("id"), str) or not call["id"]:
            raise VapiPayloadError("every tool call needs an id")
        results.append(_run(call, run_tool))
    return {"results": results}


def _run(call: dict, run_tool: RunTool) -> dict:
    entry = {"toolCallId": call["id"]}
    function = call.get("function")
    name = function.get("name") if isinstance(function, dict) else None
    if name not in FUNCTIONS:
        entry["error"] = _one_line(f"unknown_function: {name!r}")
        return entry
    arguments = function.get("arguments", {})
    if isinstance(arguments, str):
        # The documented example shows an object. A JSON string is also
        # accepted, which costs nothing if Vapi never sends one.
        try:
            arguments = json.loads(arguments or "{}")
        except ValueError:
            arguments = None
    if not isinstance(arguments, dict):
        entry["error"] = "invalid_arguments: arguments must be an object"
        return entry
    status, body = run_tool(FUNCTIONS[name], arguments)
    if status == 200:
        entry["result"] = json.dumps(body)
    else:
        entry["error"] = _one_line(f"{body.get('error')}: {body.get('message', '')}")
    return entry
