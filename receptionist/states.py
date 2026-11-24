"""The call flow as an explicit state machine.

The transition table below is the single source of truth. The engine in
flow.py refuses any move that is not listed here, and the README diagram
can be regenerated with:

    python -c "from receptionist.states import mermaid; print(mermaid())"
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, FrozenSet


class State(str, Enum):
    GREET = "greet"
    QUALIFY = "qualify"
    SERVICE_AREA = "service_area"
    OFFER_TIMES = "offer_times"
    CONTACT = "contact"
    BOOK = "book"
    HANDOFF = "handoff"
    AFTER_HOURS = "after_hours"
    ENDED = "ended"


class IllegalTransition(Exception):
    """Raised when code tries a move the table does not allow."""


TRANSITIONS: Dict[State, FrozenSet[State]] = {
    # The greeting discloses that the caller is talking to an assistant,
    # then routes on business hours.
    State.GREET: frozenset({State.QUALIFY, State.AFTER_HOURS, State.ENDED}),
    # Work out what kind of job this is.
    State.QUALIFY: frozenset({State.SERVICE_AREA, State.HANDOFF, State.ENDED}),
    # Office closed: take a message, or escalate a real emergency.
    State.AFTER_HOURS: frozenset({State.SERVICE_AREA, State.HANDOFF, State.ENDED}),
    # ZIP check. In area and open goes to times, in area and closed goes
    # straight to contact details, out of area ends the call.
    State.SERVICE_AREA: frozenset(
        {State.OFFER_TIMES, State.CONTACT, State.HANDOFF, State.ENDED}
    ),
    # Offer arrival windows. No fit falls through to a callback request.
    State.OFFER_TIMES: frozenset({State.CONTACT, State.HANDOFF, State.ENDED}),
    # Name and callback number.
    State.CONTACT: frozenset({State.BOOK, State.HANDOFF, State.ENDED}),
    # Read back and book. A lost race for the slot returns to the offers.
    State.BOOK: frozenset({State.OFFER_TIMES, State.HANDOFF, State.ENDED}),
    # Save a lead with everything collected, then transfer.
    State.HANDOFF: frozenset({State.ENDED}),
    State.ENDED: frozenset(),
}


def check_transition(current: State, new: State) -> None:
    if new not in TRANSITIONS[current]:
        raise IllegalTransition(f"{current.value} -> {new.value} is not allowed")


def mermaid() -> str:
    """Render the transition table as a mermaid state diagram."""
    lines = ["stateDiagram-v2", f"    [*] --> {State.GREET.value}"]
    for state, targets in TRANSITIONS.items():
        for target in sorted(targets, key=lambda s: list(State).index(s)):
            lines.append(f"    {state.value} --> {target.value}")
    lines.append(f"    {State.ENDED.value} --> [*]")
    return "\n".join(lines)

