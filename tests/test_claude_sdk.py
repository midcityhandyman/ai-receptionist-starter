"""The Claude backend through the real Anthropic SDK, with HTTP faked.

Skipped unless the optional SDK is installed (pip install anthropic).
The SDK builds and sends a real request to a mock transport, so these
check that the request this project builds is one the SDK accepts and
that the SDK's typed errors are classified. No network, no key, and
still not a test of what a real model returns.
"""

import json

import pytest

anthropic = pytest.importorskip("anthropic")
try:
    import httpx2 as httpx_lib
except ImportError:  # SDK releases before 1.0 are built on httpx
    import httpx as httpx_lib

from receptionist.claude_understander import ClaudeUnderstander, reply  # noqa: E402
from receptionist.understanding import CallContext  # noqa: E402

JOB = CallContext("job_description")


def understander(handler):
    client = anthropic.Anthropic(
        api_key="test-key-not-real",
        timeout=4.0,
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx_lib.MockTransport(handler)),
    )
    return ClaudeUnderstander(client=client)


def message(text, stop_reason="end_turn", content=None):
    blocks = content if content is not None else [
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {"type": "text", "text": text},
    ]
    return {
        "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
        "content": blocks, "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 12, "output_tokens": 40,
                  "cache_read_input_tokens": 900, "cache_creation_input_tokens": 0},
    }


def test_sdk_sends_the_request_and_the_reply_is_understood():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        fields = reply(intent="service_request", job_type="plumbing", urgency="routine")
        return httpx_lib.Response(200, json=message(json.dumps(fields)))

    backend = understander(handler)
    heard = backend.understand("Water keeps dripping from the tap", JOB)
    assert heard.source == "claude" and heard.job_type == "plumbing"
    assert seen["path"] == "/v1/messages"
    body = seen["body"]
    assert set(body) == {"model", "max_tokens", "system", "messages", "output_config"}
    assert body["model"] == "claude-haiku-5-5"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert json.loads(body["messages"][0]["content"]) == {
        "expecting": "job_description", "utterance": "Water keeps dripping from the tap",
    }
    assert backend.stats["cache_read_input_tokens"] == 900


def test_sdk_timeout_falls_back():
    def handler(request):
        raise httpx_lib.ReadTimeout("too slow", request=request)

    heard = understander(handler).understand("my faucet leaks", JOB)
    assert heard.fallback_reason == "timeout" and heard.job_type == "plumbing"


def test_sdk_connection_failure_falls_back():
    def handler(request):
        raise httpx_lib.ConnectError("no route", request=request)

    assert understander(handler).understand("my faucet leaks", JOB).fallback_reason == "connection_error"


@pytest.mark.parametrize(
    "status, reason",
    [(401, "auth_error"), (429, "rate_limited"), (400, "api_error_400"), (529, "api_error_529")],
)
def test_sdk_status_errors_fall_back(status, reason):
    def handler(request):
        error = {"type": "error", "error": {"type": "example_error", "message": "example"}}
        return httpx_lib.Response(status, json=error)

    heard = understander(handler).understand("my faucet leaks", JOB)
    assert heard.fallback_reason == reason and heard.source == "keyword"


def test_sdk_refusal_and_empty_content_fall_back():
    def refusal(request):
        return httpx_lib.Response(200, json=message("", stop_reason="refusal", content=[]))

    def thinking_only(request):
        blocks = [{"type": "thinking", "thinking": "", "signature": "sig"}]
        return httpx_lib.Response(200, json=message("", content=blocks))

    assert understander(refusal).understand("my faucet leaks", JOB).fallback_reason == "refusal"
    assert understander(thinking_only).understand("my faucet leaks", JOB).fallback_reason == "empty_reply"


def test_missing_credentials_fall_back_instead_of_crashing(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(name, raising=False)

    def handler(request):  # only reached if this machine has a saved login; still no network
        error = {"type": "error", "error": {"type": "authentication_error", "message": "example"}}
        return httpx_lib.Response(401, json=error)

    try:
        client = anthropic.Anthropic(
            max_retries=0,
            timeout=1.0,
            http_client=anthropic.DefaultHttpxClient(transport=httpx_lib.MockTransport(handler)),
        )
    except Exception:
        pytest.skip("this SDK release refuses to build a client without credentials")
    heard = ClaudeUnderstander(client=client).understand("my faucet leaks", JOB)
    assert heard.source == "keyword" and heard.job_type == "plumbing"
    assert heard.fallback_reason in ("no_credentials", "auth_error")
