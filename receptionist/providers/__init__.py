"""Voice provider adapters and the runner that connects one to the flow."""

from __future__ import annotations

from typing import Optional

from ..config import ConfigError, RuntimeConfig
from ..flow import Receptionist, Turn
from .base import CALL_ENDED, CALL_STARTED, UTTERANCE, CallEvent, ProviderError, VoiceProvider
from .http import HttpVoiceProvider
from .mock import MockVoiceProvider

__all__ = [
    "CallEvent",
    "CallRunner",
    "HttpVoiceProvider",
    "MockVoiceProvider",
    "ProviderError",
    "VoiceProvider",
    "get_provider",
]


def get_provider(runtime: Optional[RuntimeConfig] = None) -> VoiceProvider:
    """Build the provider named by VOICE_PROVIDER. The default is the mock."""
    runtime = runtime or RuntimeConfig()
    if runtime.voice_provider == "mock":
        return MockVoiceProvider()
    if runtime.voice_provider == "http":
        return HttpVoiceProvider(runtime.voice_api_key, runtime.voice_api_base_url)
    raise ConfigError(f"unknown VOICE_PROVIDER: {runtime.voice_provider!r}")


class CallRunner:
    """Feeds provider events into the flow and plays the result back."""

    def __init__(self, receptionist: Receptionist, provider: VoiceProvider):
        self.receptionist = receptionist
        self.provider = provider

    def dispatch(self, payload: dict) -> Optional[Turn]:
        """Handle one webhook payload. Returns None for a call ended event."""
        event = self.provider.parse_event(payload)
        if event.type == CALL_STARTED:
            turn = self.receptionist.start_call(event.call_id, event.caller_number)
        elif event.type == UTTERANCE:
            turn = self.receptionist.handle_utterance(event.call_id, event.text)
        elif event.type == CALL_ENDED:
            self.receptionist.end_call(event.call_id)
            return None
        else:
            raise ProviderError(f"unhandled event type: {event.type}")
        self._play(event.call_id, turn)
        return turn

    def _play(self, call_id: str, turn: Turn) -> None:
        if turn.say:
            self.provider.say(call_id, turn.say)
        if turn.action is None:
            return
        if turn.action.kind == "transfer":
            self.provider.transfer(call_id, turn.action.to or "")
        elif turn.action.kind == "hangup":
            self.provider.hangup(call_id)
