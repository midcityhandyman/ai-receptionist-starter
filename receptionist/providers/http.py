"""Adapter for a hosted voice platform with a JSON REST control API.

The payload and endpoint shapes here are a generic example, not any one
vendor's API. To connect a real platform, copy this file, adjust the
field names in parse_event and the paths in say, transfer and hangup,
and keep the VoiceProvider contract. Requires VOICE_API_KEY.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable, Optional

from ..config import ConfigError
from .base import CALL_ENDED, CALL_STARTED, UTTERANCE, CallEvent, ProviderError, VoiceProvider

Transport = Callable[[str, str, dict, dict], dict]

_TYPES = {
    "session.started": CALL_STARTED,
    "transcript.final": UTTERANCE,
    "session.ended": CALL_ENDED,
}


def _urllib_transport(method: str, url: str, headers: dict, body: dict) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ProviderError(f"voice platform request failed: {exc}") from exc
    return json.loads(raw) if raw else {}


class HttpVoiceProvider(VoiceProvider):
    """Payload shape:

    {"event": "transcript.final",
     "session": {"id": "...", "caller": "+1..."},
     "transcript": "..."}
    """

    name = "http"

    def __init__(self, api_key: str, base_url: str, transport: Optional[Transport] = None):
        if not api_key:
            raise ConfigError("VOICE_API_KEY is required when VOICE_PROVIDER=http")
        if not base_url:
            raise ConfigError("VOICE_API_BASE_URL is required when VOICE_PROVIDER=http")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._transport = transport or _urllib_transport

    def parse_event(self, payload: dict) -> CallEvent:
        if not isinstance(payload, dict):
            raise ProviderError("payload must be a JSON object")
        kind = _TYPES.get(payload.get("event"))
        session = payload.get("session")
        if kind is None:
            raise ProviderError(f"unknown event: {payload.get('event')!r}")
        if not isinstance(session, dict) or not session.get("id"):
            raise ProviderError("session.id is required")
        return CallEvent(
            type=kind,
            call_id=str(session["id"]),
            caller_number=str(session.get("caller") or ""),
            text=str(payload.get("transcript") or ""),
        )

    def _post(self, call_id: str, verb: str, body: dict) -> dict:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/sessions/{call_id}/{verb}"
        return self._transport("POST", url, headers, body)

    def say(self, call_id: str, text: str) -> None:
        self._post(call_id, "speak", {"text": text})

    def transfer(self, call_id: str, to: str) -> None:
        self._post(call_id, "transfer", {"to": to})

    def hangup(self, call_id: str) -> None:
        self._post(call_id, "hangup", {})
