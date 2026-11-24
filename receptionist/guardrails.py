"""Identity guardrail: the assistant always says it is an assistant.

Two rules are enforced on every outgoing line, in code, not by prompt:

1. The first thing said on a call must contain the disclosure phrase.
2. Nothing said on a call may claim to be a person.
"""

from __future__ import annotations

import re

DISCLOSURE = "automated assistant"

_FORBIDDEN = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bI(?:'m| am) (?:a |an )?(?:real |actual |live )?(?:person|human|agent|receptionist)\b",
        r"\bI(?:'m| am) not (?:a |an )?(?:robot|bot|machine|AI|automated|assistant)\b",
        r"\bthis is (?:a |an )?(?:real |actual |live )?(?:person|human)\b",
        r"\byou(?:'re| are) (?:talking|speaking) (?:to|with) (?:a |an )?(?:real |live )?(?:person|human)\b",
        r"\bmy name is\b",
    )
]


class GuardrailViolation(Exception):
    """Raised when an outgoing line breaks the identity rules."""


def has_disclosure(text: str) -> bool:
    return DISCLOSURE in text.lower()


def claims_to_be_human(text: str) -> bool:
    return any(p.search(text) for p in _FORBIDDEN)


def enforce(text: str, first_turn: bool = False) -> str:
    """Return the text unchanged, or raise if it breaks a rule."""
    if claims_to_be_human(text):
        raise GuardrailViolation(f"line claims to be a person: {text!r}")
    if first_turn and not has_disclosure(text):
        raise GuardrailViolation("the opening line must disclose the assistant")
    return text
