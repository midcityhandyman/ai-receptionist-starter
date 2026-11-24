import pytest

from receptionist import Receptionist, RuntimeConfig, ToolService
from receptionist.config import ConfigError
from receptionist.providers import (
    CallRunner, HttpVoiceProvider, MockVoiceProvider, ProviderError, get_provider,
)

from conftest import OPEN_TIME


def make_runner(provider):
    clock = lambda: OPEN_TIME  # noqa: E731
    tools = ToolService(clock=clock)
    return CallRunner(Receptionist(tools=tools, clock=clock), provider), tools


def test_default_provider_is_the_mock_and_needs_no_key():
    assert isinstance(get_provider(RuntimeConfig()), MockVoiceProvider)
    assert isinstance(get_provider(RuntimeConfig.from_env({})), MockVoiceProvider)


def test_http_provider_requires_a_key():
    with pytest.raises(ConfigError):
        get_provider(RuntimeConfig(voice_provider="http"))
    provider = get_provider(RuntimeConfig(voice_provider="http", voice_api_key="test-key"))
    assert isinstance(provider, HttpVoiceProvider)


def test_unknown_provider_is_a_config_error():
    with pytest.raises(ConfigError):
        get_provider(RuntimeConfig(voice_provider="carrier-pigeon"))


def test_mock_provider_records_speech_and_transfer():
    provider = MockVoiceProvider()
    runner, tools = make_runner(provider)
    runner.dispatch({"type": "call.started", "call_id": "m1", "from": "+15555550142"})
    turn = runner.dispatch({"type": "caller.utterance", "call_id": "m1", "text": "operator"})
    assert turn.ended
    assert len(provider.spoken("m1")) == 2
    assert "automated assistant" in provider.spoken("m1")[0]
    assert provider.transfers("m1") == ["+15555550100"]
    assert tools.leads[0]["reason"] == "caller_requested"


def test_mock_provider_call_ended_event_abandons_the_call():
    provider = MockVoiceProvider()
    runner, _ = make_runner(provider)
    runner.dispatch({"type": "call.started", "call_id": "m2"})
    assert runner.dispatch({"type": "call.ended", "call_id": "m2"}) is None
    assert runner.receptionist.session("m2").outcome == "abandoned"


@pytest.mark.parametrize(
    "payload",
    [{"type": "call.exploded", "call_id": "x"}, {"type": "call.started"}, "not a dict"],
)
def test_mock_provider_rejects_bad_payloads(payload):
    with pytest.raises(ProviderError):
        MockVoiceProvider().parse_event(payload)


def test_http_provider_translates_events_and_calls_the_platform():
    sent = []

    def transport(method, url, headers, body):
        sent.append((method, url, headers, body))
        return {}

    provider = HttpVoiceProvider("test-key", "https://voice.example.com/v1/", transport)
    runner, _ = make_runner(provider)
    runner.dispatch(
        {"event": "session.started", "session": {"id": "h1", "caller": "+15555550142"}}
    )
    runner.dispatch(
        {"event": "transcript.final", "session": {"id": "h1"},
         "transcript": "I need to speak with a person"}
    )
    urls = [url for _, url, _, _ in sent]
    assert urls == [
        "https://voice.example.com/v1/sessions/h1/speak",
        "https://voice.example.com/v1/sessions/h1/speak",
        "https://voice.example.com/v1/sessions/h1/transfer",
    ]
    assert all(h["Authorization"] == "Bearer test-key" for _, _, h, _ in sent)
    assert "automated assistant" in sent[0][3]["text"]
    assert sent[2][3] == {"to": "+15555550100"}


def test_http_provider_hangs_up_when_the_flow_ends_the_call():
    sent = []
    provider = HttpVoiceProvider(
        "k", "https://voice.example.com/v1", lambda *a: sent.append(a) or {}
    )
    runner, _ = make_runner(provider)
    runner.dispatch({"event": "session.started", "session": {"id": "h2"}})
    runner.dispatch(
        {"event": "transcript.final", "session": {"id": "h2"},
         "transcript": "leaky faucet in 00999"}
    )
    assert sent[-1][1].endswith("/sessions/h2/hangup")


@pytest.mark.parametrize(
    "payload",
    [{"event": "nope", "session": {"id": "x"}}, {"event": "session.started"}, None],
)
def test_http_provider_rejects_bad_payloads(payload):
    provider = HttpVoiceProvider("k", "https://voice.example.com/v1", lambda *a: {})
    with pytest.raises(ProviderError):
        provider.parse_event(payload)
