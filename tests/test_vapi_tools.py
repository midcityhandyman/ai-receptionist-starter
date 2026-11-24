"""The Vapi custom tool adapter, against payloads shaped like Vapi's docs.

The request below copies the structure of the example on
https://docs.vapi.ai/tools/custom-tools (read 2026-11-24), with this
project's function names and synthetic values. No Vapi account was
involved, so these tests show the adapter matches the documentation,
not that it works against the live service.
"""

import json

import pytest

from receptionist import RuntimeConfig
from receptionist.server import App
from receptionist.vapi_tools import FUNCTIONS, VapiPayloadError, handle_tool_calls

from conftest import OPEN_TIME

SECRET = {"X-Tool-Secret": "s3"}


def tool_call(call_id, name, arguments):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


def tool_calls_message(*calls):
    """A "tool-calls" server message with every documented top level field."""
    return {
        "message": {
            "timestamp": 1678901234567,
            "type": "tool-calls",
            "toolCallList": list(calls),
            "toolWithToolCallList": [
                {
                    "type": "function",
                    "function": {
                        "name": call["function"]["name"],
                        "parameters": {"type": "object", "properties": {}},
                        "description": "Example tool",
                    },
                    "server": {"url": "https://tools.example.com/vapi/tools"},
                    "messages": [],
                    "toolCall": call,
                }
                for call in calls
            ],
            "artifact": {"messages": []},
            "assistant": {"name": "Example Assistant", "model": {}, "voice": {}},
            "call": {"id": "call-uuid", "orgId": "org-uuid", "type": "webCall", "assistant": {}},
        }
    }


@pytest.fixture
def app():
    return App(runtime=RuntimeConfig(tool_shared_secret="s3"), clock=lambda: OPEN_TIME)


def post(app, body, headers=SECRET):
    return app.handle("POST", "/vapi/tools", headers, json.dumps(body).encode("utf-8"))


def test_availability_call_returns_a_flat_string_result(app):
    body = tool_calls_message(
        tool_call("toolu_01", "check_availability", {"job_type": "plumbing", "zip": "00102", "limit": 2})
    )
    status, payload = post(app, body)
    assert status == 200
    assert list(payload) == ["results"]
    (entry,) = payload["results"]
    assert set(entry) == {"toolCallId", "result"}
    assert entry["toolCallId"] == "toolu_01"
    assert isinstance(entry["result"], str) and "\n" not in entry["result"]
    result = json.loads(entry["result"])
    assert result["in_service_area"] is True and len(result["slots"]) == 2


def test_booking_through_vapi_reaches_the_same_tool_service(app):
    args = {"slot_id": "2030-01-08T08:00", "job_type": "plumbing", "name": "Alex Sample",
            "phone": "555-555-0142", "zip": "00102"}
    status, payload = post(app, tool_calls_message(tool_call("c1", "book_appointment", args)))
    assert status == 200
    assert json.loads(payload["results"][0]["result"])["confirmation"] == "BK-0001"
    assert len(app.tools.bookings) == 1


def test_a_failed_tool_is_http_200_with_an_error_string(app):
    args = {"slot_id": "2030-01-08T08:00", "job_type": "plumbing", "name": "Alex Sample",
            "phone": "555-555-0142", "zip": "00999"}
    status, payload = post(app, tool_calls_message(tool_call("c1", "book_appointment", args)))
    assert status == 200
    (entry,) = payload["results"]
    assert set(entry) == {"toolCallId", "error"}
    assert isinstance(entry["error"], str) and entry["error"].startswith("out_of_area")
    assert "\n" not in entry["error"]
    assert app.tools.bookings == {}


def test_missing_argument_is_reported_per_call_not_as_an_http_error(app):
    status, payload = post(
        app, tool_calls_message(tool_call("c1", "check_availability", {"job_type": "plumbing"}))
    )
    assert status == 200
    assert payload["results"][0]["error"].startswith("missing_field")


def test_several_calls_get_one_result_each_matched_by_id(app):
    body = tool_calls_message(
        tool_call("a", "check_availability", {"job_type": "hvac", "zip": "00104"}),
        tool_call("b", "create_lead", {"reason": "callback_requested", "name": "Riley Testcase",
                                       "phone": "555-555-0155"}),
        tool_call("c", "get_weather", {"location": "Sampleton"}),
    )
    status, payload = post(app, body)
    assert status == 200
    by_id = {entry["toolCallId"]: entry for entry in payload["results"]}
    assert set(by_id) == {"a", "b", "c"}
    assert "result" in by_id["a"] and "result" in by_id["b"]
    assert by_id["c"]["error"].startswith("unknown_function")
    assert all(("result" in e) != ("error" in e) for e in payload["results"])
    assert app.tools.leads[0]["reason"] == "callback_requested"


def test_arguments_sent_as_a_json_string_are_accepted(app):
    body = tool_calls_message(
        tool_call("c1", "check_availability", json.dumps({"job_type": "hvac", "zip": "00104"}))
    )
    assert "result" in post(app, body)[1]["results"][0]
    bad = tool_calls_message(tool_call("c2", "check_availability", "not json"))
    assert post(app, bad)[1]["results"][0]["error"].startswith("invalid_arguments")


def test_the_shared_secret_is_required(app):
    body = tool_calls_message(tool_call("c1", "check_availability", {"job_type": "hvac", "zip": "00104"}))
    assert post(app, body, headers={})[0] == 401
    assert post(app, body, headers={"x-tool-secret": "s3"})[0] == 200


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"message": "tool-calls"},
        {"message": {"type": "end-of-call-report"}},
        {"message": {"type": "tool-calls"}},
        {"message": {"type": "tool-calls", "toolCallList": []}},
        {"message": {"type": "tool-calls", "toolCallList": [{"type": "function"}]}},
    ],
)
def test_payloads_that_are_not_tool_calls_are_rejected(app, body):
    status, payload = post(app, body)
    assert status == 400 and payload["error"] == "invalid_event"
    with pytest.raises(VapiPayloadError):
        handle_tool_calls(body, lambda path, args: (200, {}))


def test_every_function_maps_to_an_existing_tool_endpoint(app):
    for path in FUNCTIONS.values():
        assert app.handle("POST", path, SECRET, b"{}")[0] != 404
