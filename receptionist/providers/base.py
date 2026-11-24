"""The contract every voice provider adapter implements.

An adapter does two jobs: it turns the platform's webhook payloads into
CallEvent objects, and it sends the assistant's speech and call control
actions back to the platform.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

CALL_STARTED = "call_started"
UTTERANCE = "utterance"
CALL_ENDED = "call_ended"


class ProviderError(Exception):
    """A payload could not be parsed or a platform request failed."""


@dataclass(frozen=True)
class CallEvent:
    type: str
    call_id: str
    caller_number: str = ""
    text: str = ""


class VoiceProvider(ABC):
    name = "base"

    @abstractmethod
    def parse_event(self, payload: dict) -> CallEvent:
        """Translate one webhook payload from the platform."""

    @abstractmethod
    def say(self, call_id: str, text: str) -> None:
        """Speak text to the caller."""

    @abstractmethod
    def transfer(self, call_id: str, to: str) -> None:
        """Transfer the live call to a phone number."""

    @abstractmethod
    def hangup(self, call_id: str) -> None:
        """End the call."""
