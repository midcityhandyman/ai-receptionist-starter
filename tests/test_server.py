import json
import threading
import urllib.error
import urllib.request

import pytest

from receptionist import RuntimeConfig
from receptionist.server import App, make_server

from conftest import OPEN_TIME

SECRET = {"X-Tool-Secret": "s3"}
BOOKING = {
    "slot_id": "2030-01-08T08:00", "job_type": "plumbing", "name": "Alex Sample",
    "phone": "555-555-0142", "zip": "00102",
}


@pytest.fixture
def app():
    return App(runtime=RuntimeConfig(tool_shared_secret="s3"), clock=lambda: OPEN_TIME)


def post(app, path, body, headers=SECRET):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    return app.handle("POST", path, headers, raw)


def test_health_needs_no_secret(app):
    assert app.handle("GET", "/health", {}, b"") == (
        200, {"status": "ok", "voice_provider": "mock"},
    )


def test_tools_require_the_shared_secret(app):
    body = {"job_type": "plumbing", "zip": "00102"}
    assert post(app, "/tools/availability", body, headers={})[0] == 401
    assert post(app, "/tools/availability", body, headers={"X-Tool-Secret": "wrong"})[0] == 401
    assert post(app, "/tools/availability", body, headers={"x-tool-secret": "s3"})[0] == 200
    event = {"type": "call.started", "call_id": "c"}
    assert post(app, "/voice/events", event, headers={})[0] == 401


def test_no_secret_configured_means_open_endpoints():
    open_app = App(clock=lambda: OPEN_TIME)
    body = {"job_type": "plumbing", "zip": "00102"}
    assert post(open_app, "/tools/availability", body, {})[0] == 200


def test_availability_book_and_conflict(app):
    body = {"job_type": "plumbing", "zip": "00102", "limit": 2}
    status, result = post(app, "/tools/availability", body)
    assert status == 200 and len(result["slots"]) == 2
    assert result["slots"][0]["slot_id"] == BOOKING["slot_id"]
    status, booked = post(app, "/tools/book", BOOKING)
    assert status == 200 and booked["confirmation"] == "BK-0001"
    status, error = post(app, "/tools/book", BOOKING)
    assert status == 409 and error["error"] == "slot_unavailable"


def test_create_lead_endpoint(app):
    body = {"reason": "callback_requested", "phone": "5555550155"}
    status, lead = post(app, "/tools/create-lead", body)
    assert status == 200 and lead["lead_id"] == "LD-0001"
    assert app.tools.leads[0]["phone"] == "5555550155"


@pytest.mark.parametrize(
    "path, body, status, error",
    [
        ("/tools/availability", {"zip": "00102"}, 400, "missing_field"),
        ("/tools/availability", {"job_type": "plumbing", "zip": "00102", "x": 1}, 400, "unknown_field"),
        ("/tools/availability", {"job_type": "plumbing", "zip": 102}, 400, "invalid_zip"),
        ("/tools/availability", {"job_type": "plumbing", "zip": "00102", "limit": "3"}, 400, "invalid_limit"),
        ("/tools/availability", b"{not json", 400, "invalid_json"),
        ("/tools/availability", b"[1, 2]", 400, "invalid_json"),
        ("/tools/book", dict(BOOKING, slot_id="nope"), 404, "unknown_slot"),
        ("/tools/book", dict(BOOKING, zip="00999"), 422, "out_of_area"),
        ("/tools/create-lead", {"reason": "bogus"}, 400, "invalid_reason"),
        ("/tools/nothing", {}, 404, "not_found"),
        ("/voice/events", {"type": "bogus", "call_id": "c"}, 400, "invalid_event"),
        ("/voice/events", {"type": "caller.utterance", "call_id": "ghost", "text": "hi"}, 404, "unknown_call"),
    ],
)
def test_error_responses(app, path, body, status, error):
    got_status, payload = post(app, path, body)
    assert (got_status, payload["error"]) == (status, error)


def test_wrong_method(app):
    assert app.handle("GET", "/tools/book", SECRET, b"")[0] == 405
    assert app.handle("POST", "/health", SECRET, b"")[0] == 405


def test_voice_events_drive_a_whole_call(app):
    def event(kind, text=""):
        body = {"type": kind, "call_id": "v1", "from": "+15555550142", "text": text}
        return post(app, "/voice/events", body)[1]

    first = event("call.started")
    assert "automated assistant" in first["say"] and first["state"] == "qualify"
    for line in ["leaky faucet", "00102", "the first one", "Alex Sample", "yes"]:
        reply = event("caller.utterance", line)
    assert reply["state"] == "book" and reply["action"] is None
    last = event("caller.utterance", "yes")
    assert last["ended"] and last["action"] == {"type": "hangup"}
    assert event("call.ended") == {"status": "ended"}
    assert len(app.tools.bookings) == 1


def test_real_http_round_trip(app):
    server = make_server(app, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def request(method, path, body=None, headers=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(base + path, data=data, headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    try:
        assert request("GET", "/health")[0] == 200
        body = {"job_type": "hvac", "zip": "00104"}
        assert request("POST", "/tools/availability", body)[0] == 401
        status, result = request("POST", "/tools/availability", body, SECRET)
        assert status == 200 and len(result["slots"]) == 3
        status, booked = request("POST", "/tools/book", BOOKING, SECRET)
        assert status == 200 and booked["status"] == "booked"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
