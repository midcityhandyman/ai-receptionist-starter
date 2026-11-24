"""The call flow engine.

One Receptionist instance handles many calls. Each call has a CallSession
that sits in exactly one State. Every caller utterance is routed to the
handler for the current state, which returns what to say next and, when
the call is over, an action for the voice platform (transfer or hang up).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from . import guardrails, nlu, prompts
from .config import JOB_TYPES, BusinessConfig
from .states import State, check_transition
from .tools import ToolError, ToolService


class UnknownCall(KeyError):
    """Raised when an event arrives for a call that was never started."""


@dataclass
class Action:
    """What the voice platform should do after speaking."""

    kind: str  # "transfer" or "hangup"
    to: Optional[str] = None

    def to_dict(self) -> dict:
        return {"type": self.kind, "to": self.to} if self.to else {"type": self.kind}


@dataclass
class Turn:
    """The assistant's response to one event."""

    say: str
    state: State
    action: Optional[Action] = None
    ended: bool = False

    def to_dict(self) -> dict:
        return {
            "say": self.say,
            "state": self.state.value,
            "action": self.action.to_dict() if self.action else None,
            "ended": self.ended,
        }


@dataclass
class CallSession:
    call_id: str
    caller_number: str = ""
    after_hours: bool = False
    state: State = State.GREET
    path: List[State] = field(default_factory=lambda: [State.GREET])
    # Ordered log of everything that happened: (kind, text) where kind is
    # assistant, caller, state, tool, action or note.
    events: List[Tuple[str, str]] = field(default_factory=list)
    job_type: Optional[str] = None
    description: str = ""
    zip_code: Optional[str] = None
    offered: List[dict] = field(default_factory=list)
    offer_pages: int = 0
    slot: Optional[dict] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    contact_step: str = "name"
    retries: int = 0
    last_question: str = ""
    assistant_turns: int = 0
    outcome: Optional[str] = None
    handoff_reason: Optional[str] = None
    booking: Optional[dict] = None
    lead: Optional[dict] = None
    transfer_to: Optional[str] = None

    @property
    def transcript(self) -> List[Tuple[str, str]]:
        return [(k, t) for k, t in self.events if k in ("assistant", "caller")]

    def summary(self) -> dict:
        return {
            "call_id": self.call_id,
            "outcome": self.outcome,
            "final_state": self.state.value,
            "path": [s.value for s in self.path],
            "after_hours": self.after_hours,
            "job_type": self.job_type,
            "zip": self.zip_code,
            "name": self.name,
            "confirmation": self.booking["confirmation"] if self.booking else None,
            "lead_id": self.lead["lead_id"] if self.lead else None,
            "transfer_to": self.transfer_to,
            "handoff_reason": self.handoff_reason,
        }


class Receptionist:
    def __init__(
        self,
        config: Optional[BusinessConfig] = None,
        tools: Optional[ToolService] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.config = config or BusinessConfig()
        self.clock = clock or datetime.now
        self.tools = tools or ToolService(self.config, self.clock)
        self._sessions: Dict[str, CallSession] = {}
        self._handlers = {
            State.QUALIFY: self._on_qualify,
            State.AFTER_HOURS: self._on_after_hours,
            State.SERVICE_AREA: self._on_service_area,
            State.OFFER_TIMES: self._on_offer_times,
            State.CONTACT: self._on_contact,
            State.BOOK: self._on_book,
        }

    # ----- public API -----

    def start_call(self, call_id: str, caller_number: str = "") -> Turn:
        """Answer a new call with the disclosure greeting."""
        session = CallSession(call_id=call_id, caller_number=caller_number or "")
        session.after_hours = not self.config.is_open(self.clock())
        self._sessions[call_id] = session
        company = self.config.company_name
        if session.after_hours:
            self._move(session, State.AFTER_HOURS)
            greeting = prompts.AFTER_HOURS_GREETING.format(company=company)
            return self._ask(session, greeting, prompts.ASK_AFTER_HOURS)
        self._move(session, State.QUALIFY)
        return self._ask(session, prompts.GREETING.format(company=company), prompts.ASK_JOB)

    def handle_utterance(self, call_id: str, text: str) -> Turn:
        """Process one thing the caller said."""
        session = self.session(call_id)
        if session.state is State.ENDED:
            return Turn("", State.ENDED, ended=True)
        text = (text or "").strip()
        session.events.append(("caller", text or "(silence)"))
        if not text:
            return self._retry(session, prompts.DID_NOT_CATCH, "no_input")
        # Interrupts that apply in every state, checked before the handler.
        if nlu.is_identity_question(text):
            return self._ask(session, prompts.IDENTITY, session.last_question)
        if nlu.is_emergency(text):
            session.description = text
            session.job_type = session.job_type or nlu.job_type(text)
            return self._handoff(session, "emergency")
        if nlu.wants_human(text):
            return self._handoff(session, "caller_requested")
        return self._handlers[session.state](session, text)

    def end_call(self, call_id: str) -> CallSession:
        """The caller hung up, or the platform reports the call is over."""
        session = self.session(call_id)
        if session.state is not State.ENDED:
            session.events.append(("note", "caller hung up"))
            if session.job_type or session.description:
                self._lead(session, "abandoned")
            session.outcome = "abandoned"
            self._move(session, State.ENDED)
        return session

    def session(self, call_id: str) -> CallSession:
        try:
            return self._sessions[call_id]
        except KeyError:
            raise UnknownCall(call_id) from None

    # ----- state handlers -----

    def _on_qualify(self, s: CallSession, text: str) -> Turn:
        job = nlu.job_type(text)
        if job is None:
            # Keep what was said so a human picking up the lead has context.
            s.description = text
            return self._retry(
                s, prompts.QUALIFY_RETRY, "could_not_qualify", prompts.ASK_JOB_RETRY
            )
        s.job_type = job
        s.description = text
        ack = prompts.JOB_ACK.format(job=JOB_TYPES[job])
        return self._enter_service_area(s, text, ack)

    def _on_after_hours(self, s: CallSession, text: str) -> Turn:
        message = nlu.strip_emergency_negation(text)
        job = nlu.job_type(message)
        if job is None and len(message.split()) < 4:
            # "No" or "not an emergency" on its own: still need the message.
            return self._retry(s, "Okay.", "no_input", prompts.ASK_AFTER_HOURS)
        s.job_type = job
        s.description = text
        return self._enter_service_area(s, text, prompts.MESSAGE_ACK)

    def _enter_service_area(self, s: CallSession, text: str, ack: str) -> Turn:
        self._move(s, State.SERVICE_AREA)
        if nlu.extract_zip(text):
            # The caller already gave the ZIP while describing the job.
            return self._check_zip(s, nlu.extract_zip(text), ack)
        return self._ask(s, ack, prompts.ASK_ZIP)

    def _on_service_area(self, s: CallSession, text: str) -> Turn:
        zip_code = nlu.extract_zip(text)
        if zip_code is None:
            return self._retry(s, prompts.ZIP_RETRY, "no_input")
        return self._check_zip(s, zip_code, "")

    def _check_zip(self, s: CallSession, zip_code: str, ack: str) -> Turn:
        s.zip_code = zip_code
        if not self.tools.in_service_area(zip_code):
            self._lead(s, "out_of_area")
            text = prompts.OUT_OF_AREA.format(zip=zip_code, company=self.config.company_name)
            return self._end(s, text, "out_of_area")
        if s.after_hours:
            self._move(s, State.CONTACT)
            return self._ask(s, ack, prompts.ASK_NAME)
        return self._offer_times(s, prompts.OFFER_INTRO, ack)

    def _offer_times(self, s: CallSession, template: str, ack: str = "", after: Optional[str] = None) -> Turn:
        """Fetch open windows and move to OFFER_TIMES, or fall back to a callback."""
        result = self._tool(
            s, "availability", job_type=s.job_type, zip_code=s.zip_code, limit=3, after=after
        )
        slots = result.get("slots", [])
        if not slots:
            s.slot = None
            if s.name and s.phone:
                # Reached from BOOK with contact details already collected.
                self._lead(s, "callback_requested")
                text = prompts.CALLBACK_REQUESTED.format(name=s.name)
                return self._end(s, f"{prompts.NO_SLOTS} {text}", "callback_requested")
            self._move(s, State.CONTACT)
            preface = " ".join(p for p in (ack, prompts.NO_SLOTS) if p)
            return self._ask(s, preface, prompts.ASK_NAME)
        s.offered = slots
        s.slot = None
        if s.state is not State.OFFER_TIMES:
            self._move(s, State.OFFER_TIMES)
        spoken = "; ".join(slot["label"] for slot in slots)
        preface = " ".join(p for p in (ack, template.format(slots=spoken)) if p)
        return self._ask(s, preface, prompts.ASK_SLOT)

    def _on_offer_times(self, s: CallSession, text: str) -> Turn:
        choice = nlu.pick_slot(text, s.offered)
        if choice is None:
            return self._retry(s, prompts.DID_NOT_CATCH, "no_input")
        if choice == nlu.NONE_OF_THESE:
            if s.offer_pages >= 1:
                # Two rounds offered and nothing fit: take a callback request.
                self._move(s, State.CONTACT)
                return self._ask(s, prompts.NO_SLOTS, prompts.ASK_NAME)
            s.offer_pages += 1
            return self._offer_times(s, prompts.OFFER_MORE, after=s.offered[-1]["slot_id"])
        s.slot = s.offered[choice]
        self._move(s, State.CONTACT)
        if s.name and s.phone:
            # Contact details survive a trip back from BOOK.
            return self._contact_done(s)
        return self._ask(s, f"{s.slot['label']}, got it.", prompts.ASK_NAME)

    def _on_contact(self, s: CallSession, text: str) -> Turn:
        if s.contact_step == "name":
            name = nlu.extract_name(text)
            if name is None:
                return self._retry(s, prompts.NAME_RETRY, "no_input", prompts.ASK_NAME_AGAIN)
            s.name = name
            s.retries = 0
            ack = prompts.NAME_ACK.format(name=name)
            caller_id = nlu.normalize_phone(s.caller_number)
            if caller_id:
                s.contact_step = "confirm_phone"
                question = prompts.CONFIRM_PHONE.format(phone=nlu.format_phone(caller_id))
                return self._ask(s, ack, question)
            s.contact_step = "ask_phone"
            return self._ask(s, ack, prompts.ASK_PHONE)

        phone = nlu.extract_phone(text)
        if phone is None and s.contact_step == "confirm_phone":
            answer = nlu.yes_no(text)
            if answer is True:
                phone = nlu.normalize_phone(s.caller_number)
            elif answer is False:
                s.contact_step = "ask_phone"
                s.retries = 0
                return self._ask(s, "Okay.", prompts.ASK_PHONE)
        if phone is None:
            return self._retry(s, prompts.PHONE_RETRY, "no_input")
        s.phone = phone
        return self._contact_done(s)

    def _contact_done(self, s: CallSession) -> Turn:
        if s.slot is None:
            # No appointment to book: after hours message or callback request.
            reason = "after_hours" if s.after_hours else "callback_requested"
            self._lead(s, reason)
            template = prompts.LEAD_CAPTURED if s.after_hours else prompts.CALLBACK_REQUESTED
            outcome = "lead_captured" if s.after_hours else "callback_requested"
            return self._end(s, template.format(name=s.name), outcome)
        self._move(s, State.BOOK)
        question = prompts.CONFIRM_BOOKING.format(
            job=JOB_TYPES[s.job_type], slot=s.slot["label"], zip=s.zip_code, name=s.name
        )
        return self._ask(s, "", question)

    def _on_book(self, s: CallSession, text: str) -> Turn:
        answer = nlu.yes_no(text)
        if answer is None:
            return self._retry(s, prompts.BOOK_UNCLEAR, "no_input")
        if answer is False:
            return self._offer_times(s, prompts.OFFER_AGAIN)
        result = self._tool(
            s,
            "book",
            slot_id=s.slot["slot_id"],
            job_type=s.job_type,
            name=s.name,
            phone=s.phone,
            zip_code=s.zip_code,
            description=s.description,
            idempotency_key=f"{s.call_id}:{s.slot['slot_id']}",
        )
        if result.get("error") == "slot_unavailable":
            return self._offer_times(s, prompts.SLOT_TAKEN)
        if "error" in result:
            return self._handoff(s, "other")
        s.booking = result
        text = prompts.BOOKED.format(
            confirmation=result["confirmation"],
            slot=s.slot["label"],
            company=self.config.company_name,
        )
        return self._end(s, text, "booked")

    # ----- handoff -----

    def _handoff(self, s: CallSession, reason: str) -> Turn:
        """Save what we know as a lead, then transfer if anyone can answer."""
        s.handoff_reason = reason
        self._move(s, State.HANDOFF)
        self._lead(s, reason, urgency="urgent" if reason == "emergency" else "normal")
        if reason == "emergency":
            number = self.config.on_call_number if s.after_hours else self.config.handoff_number
            target = "on-call technician" if s.after_hours else "office team"
            text = prompts.EMERGENCY.format(target=target)
            return self._end(s, text, "emergency_transfer", Action("transfer", number))
        if s.after_hours:
            return self._end(s, prompts.HANDOFF_CLOSED, "callback_requested")
        text = prompts.HANDOFF if reason == "caller_requested" else prompts.HANDOFF_STUCK
        return self._end(s, text, "handed_off", Action("transfer", self.config.handoff_number))

    # ----- plumbing -----

    def _move(self, s: CallSession, new: State) -> None:
        check_transition(s.state, new)
        s.events.append(("state", f"{s.state.value} -> {new.value}"))
        s.state = new
        s.path.append(new)
        s.retries = 0

    def _reply(self, s: CallSession, text: str, action: Optional[Action] = None, ended: bool = False) -> Turn:
        guardrails.enforce(text, first_turn=s.assistant_turns == 0)
        s.assistant_turns += 1
        s.events.append(("assistant", text))
        if action is not None:
            detail = f"transfer to {action.to}" if action.kind == "transfer" else action.kind
            s.events.append(("action", detail))
            if action.kind == "transfer":
                s.transfer_to = action.to
        return Turn(text, s.state, action, ended)

    def _ask(self, s: CallSession, preface: str, question: str) -> Turn:
        s.last_question = question
        return self._reply(s, " ".join(p for p in (preface, question) if p))

    def _retry(self, s: CallSession, preface: str, reason: str, question: Optional[str] = None) -> Turn:
        """Ask again, or hand off once the caller has missed too many times."""
        s.retries += 1
        if s.retries >= self.config.max_retries:
            return self._handoff(s, reason)
        return self._ask(s, preface, question or s.last_question)

    def _end(self, s: CallSession, text: str, outcome: str, action: Optional[Action] = None) -> Turn:
        s.outcome = outcome
        self._move(s, State.ENDED)
        return self._reply(s, text, action or Action("hangup"), ended=True)

    def _lead(self, s: CallSession, reason: str, urgency: str = "normal") -> None:
        phone = s.phone or nlu.normalize_phone(s.caller_number)
        result = self._tool(
            s,
            "create_lead",
            reason=reason,
            job_type=s.job_type,
            description=s.description,
            name=s.name,
            phone=phone,
            zip_code=s.zip_code,
            urgency=urgency,
            call_id=s.call_id,
        )
        if "error" not in result:
            s.lead = result

    def _tool(self, s: CallSession, tool: str, /, **args) -> dict:
        """Call a tool, log the call on the session, never raise ToolError."""
        try:
            result = getattr(self.tools, tool)(**args)
        except ToolError as exc:
            result = exc.to_dict()
        shown = {k: v for k, v in args.items() if v not in (None, "") and k != "call_id"}
        s.events.append(("tool", f"{tool} {json.dumps(shown)} -> {_summarize(result)}"))
        return result


def _summarize(result: dict) -> str:
    if "error" in result:
        return f"error: {result['error']}"
    if "slots" in result:
        return f"{len(result['slots'])} open windows"
    if "confirmation" in result:
        return f"booked {result['confirmation']}"
    if "lead_id" in result:
        return f"lead {result['lead_id']}"
    return "ok"
