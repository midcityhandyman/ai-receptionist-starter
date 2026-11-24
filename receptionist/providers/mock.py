"""Offline voice provider. Records everything instead of placing calls."""

from __future__ import annotations

from typing import Dict, List, Tuple

from .base import CALL_ENDED, CALL_STARTED, UTTERANCE, CallEvent, ProviderError, VoiceProvider

_TYPES = {
    "call.started": CALL_STARTED,
    "caller.utterance": UTTERANCE,
    "call.ended": CALL_ENDED,
}


class MockVoiceProvider(VoiceProvider):
    """Payload shape: {"type": ..., "call_id": ..., "from": ..., "text": ...}"""

    name = "mock"

    def __init__(self) -> None:
        self.calls: Dict[str, List[Tuple[str, str]]] = {}

    def parse_event(self, payload: dict) -> CallEvent:
        if not isinstance(payload, dict):
            raise ProviderError("payload must be a JSON object")
        kind = _TYPES.get(payload.get("type"))
        call_id = payload.get("call_id")
        if kind is None:
            raise ProviderError(f"unknown event type: {payload.get('type')!r}")
        if not isinstance(call_id, str) or not call_id:
            raise ProviderError("call_id is required")
        return CallEvent(
            type=kind,
            call_id=call_id,
            caller_number=str(payload.get("from") or ""),
            text=str(payload.get("text") or ""),
        )

    def _record(self, call_id: str, kind: str, detail: str) -> None:
        self.calls.setdefault(call_id, []).append((kind, detail))

    def say(self, call_id: str, text: str) -> None:
        self._record(call_id, "say", text)

    def transfer(self, call_id: str, to: str) -> None:
        self._record(call_id, "transfer", to)

    def hangup(self, call_id: str) -> None:
        self._record(call_id, "hangup", "")

    def spoken(self, call_id: str) -> List[str]:
        return [d for k, d in self.calls.get(call_id, []) if k == "say"]

    def transfers(self, call_id: str) -> List[str]:
        return [d for k, d in self.calls.get(call_id, []) if k == "transfer"]
