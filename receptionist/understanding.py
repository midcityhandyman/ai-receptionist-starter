"""Caller understanding behind one interface.

The flow never reads raw text for meaning. It asks an Understander what
the caller said and gets back an Understanding: plain extracted facts,
no decisions. Two implementations exist:

- KeywordUnderstander: the rules in nlu.py. Default, offline, no key.
- ClaudeUnderstander (claude_understander.py): a language model that
  fills the same structure, with the rules as its fallback.

What happens next (state changes, the service area check, booking,
after hours handling, handoff) is decided in flow.py from these facts,
never by the backend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from . import nlu
from .config import ConfigError
from .nlu import TimeWindow

KEYWORD = "keyword"
CLAUDE = "claude"
BACKENDS = (KEYWORD, CLAUDE)
# The fast tier suits a live call. Override with UNDERSTANDING_MODEL.
DEFAULT_MODEL = "claude-haiku-5-5"
DEFAULT_TIMEOUT_SECONDS = 4.0

# What the assistant just asked for. This label and the caller's words
# are the only call state an understanding backend is ever given.
EXPECTING = (
    "job_description",
    "after_hours_message",
    "zip_code",
    "time_choice",
    "name",
    "phone_confirmation",
    "phone_number",
    "booking_confirmation",
)


@dataclass(frozen=True)
class CallContext:
    """The minimal call state a backend may see."""

    expecting: str

    def __post_init__(self) -> None:
        if self.expecting not in EXPECTING:
            raise ValueError(f"unknown expecting label: {self.expecting!r}")


@dataclass(frozen=True)
class Understanding:
    """Facts extracted from one caller utterance."""

    asks_if_human: bool = False
    wants_human: bool = False
    emergency: bool = False
    job_type: Optional[str] = None
    zip_code: Optional[str] = None
    place_name: Optional[str] = None
    yes_no: Optional[bool] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    window: TimeWindow = field(default_factory=TimeWindow)
    # Bookkeeping, shown in the call log.
    source: str = KEYWORD
    intent: Optional[str] = None
    confidence: Optional[str] = None
    fallback_reason: Optional[str] = None
    detail: str = ""


class Understander(ABC):
    name = "base"

    @abstractmethod
    def understand(self, text: str, context: CallContext) -> Understanding:
        """Extract what the caller said. Must not raise."""


class KeywordUnderstander(Understander):
    """The deterministic rules in nlu.py."""

    name = KEYWORD

    def understand(self, text: str, context: CallContext) -> Understanding:
        return Understanding(
            asks_if_human=nlu.is_identity_question(text),
            wants_human=nlu.wants_human(text),
            emergency=nlu.is_emergency(text),
            job_type=nlu.job_type(text),
            zip_code=nlu.extract_zip(text),
            yes_no=nlu.yes_no(text),
            name=nlu.extract_name(text),
            phone=nlu.extract_phone(text),
            window=nlu.extract_window(text),
            source=KEYWORD,
        )


def get_understander(
    backend: str = KEYWORD,
    model: str = DEFAULT_MODEL,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    client=None,
) -> Understander:
    """Build the named backend. The default is the keyword rules.

    client is only used by the Claude backend; pass a fake in tests.
    """
    if backend == KEYWORD:
        return KeywordUnderstander()
    if backend == CLAUDE:
        from .claude_understander import ClaudeUnderstander

        return ClaudeUnderstander(model=model, timeout_seconds=timeout_seconds, client=client)
    raise ConfigError(
        f"unknown UNDERSTANDING_BACKEND: {backend!r} (use one of {', '.join(BACKENDS)})"
    )
