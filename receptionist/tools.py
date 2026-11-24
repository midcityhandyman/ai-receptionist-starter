"""The three tools the voice flow relies on: availability, book, create lead.

ToolService is plain Python with an in-memory store. The HTTP layer in
server.py exposes the same methods so a hosted voice platform can call
them as tool endpoints.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

from . import nlu
from .config import JOB_TYPES, BusinessConfig

_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_MONTHS = [
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
]

LEAD_REASONS = {
    "after_hours", "callback_requested", "caller_requested", "emergency",
    "could_not_qualify", "no_input", "out_of_area", "abandoned", "other",
}


class ToolError(Exception):
    """A tool call failed in a way the caller of the tool should handle."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def to_dict(self) -> dict:
        return {"error": self.code, "message": self.message}


def _hour_12(hour: int) -> int:
    return (hour - 1) % 12 + 1


def window_label(start: datetime, end: datetime) -> str:
    """Speakable label such as 'Tuesday, January 8, between 8 and 10 AM'."""
    start_m = "AM" if start.hour < 12 else "PM"
    end_m = "AM" if end.hour < 12 else "PM"
    if start_m == end_m:
        window = f"between {_hour_12(start.hour)} and {_hour_12(end.hour)} {end_m}"
    else:
        window = f"between {_hour_12(start.hour)} {start_m} and {_hour_12(end.hour)} {end_m}"
    day = f"{_WEEKDAYS[start.weekday()]}, {_MONTHS[start.month - 1]} {start.day}"
    return f"{day}, {window}"


class ToolService:
    def __init__(
        self,
        config: Optional[BusinessConfig] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.config = config or BusinessConfig()
        self.clock = clock or datetime.now
        self.bookings: Dict[str, dict] = {}
        self.leads: List[dict] = []
        self._idempotency: Dict[str, str] = {}
        self._lock = threading.Lock()

    # ----- helpers -----

    def in_service_area(self, zip_code: str) -> bool:
        return zip_code in self.config.service_zips

    def _all_slots(self) -> List[dict]:
        """Every arrival window in the lookahead, starting tomorrow."""
        today = self.clock().replace(hour=0, minute=0, second=0, microsecond=0)
        slots = []
        for offset in range(1, self.config.lookahead_days + 1):
            day = today + timedelta(days=offset)
            for hour in self.config.window_starts_for(day.weekday()):
                start = day.replace(hour=hour)
                end = start + timedelta(hours=self.config.window_hours)
                slots.append(
                    {
                        "slot_id": start.strftime("%Y-%m-%dT%H:%M"),
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "label": window_label(start, end),
                    }
                )
        return slots

    def _taken(self, slot_id: str) -> int:
        return sum(1 for b in self.bookings.values() if b["slot_id"] == slot_id)

    @staticmethod
    def _require_zip(zip_code: object) -> str:
        if not isinstance(zip_code, str) or not (len(zip_code) == 5 and zip_code.isdigit()):
            raise ToolError("invalid_zip", "zip must be a five digit string")
        return zip_code

    @staticmethod
    def _require_job(job_type: object) -> str:
        if job_type not in JOB_TYPES:
            raise ToolError(
                "invalid_job_type", "job_type must be one of: " + ", ".join(JOB_TYPES)
            )
        return str(job_type)

    # ----- tools -----

    def availability(
        self,
        job_type: str,
        zip_code: str,
        limit: int = 3,
        after: Optional[str] = None,
    ) -> dict:
        """Open arrival windows, soonest first. `after` pages past a slot id."""
        self._require_job(job_type)
        zip_code = self._require_zip(zip_code)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 10:
            raise ToolError("invalid_limit", "limit must be an integer from 1 to 10")
        if not self.in_service_area(zip_code):
            return {"in_service_area": False, "slots": []}
        with self._lock:
            open_slots = [
                s
                for s in self._all_slots()
                if self._taken(s["slot_id"]) < self.config.crews_per_window
                and (after is None or s["slot_id"] > after)
            ]
        return {"in_service_area": True, "slots": open_slots[:limit]}

    def book(
        self,
        slot_id: str,
        job_type: str,
        name: str,
        phone: str,
        zip_code: str,
        description: str = "",
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """Book one arrival window. Safe to retry with an idempotency key."""
        self._require_job(job_type)
        zip_code = self._require_zip(zip_code)
        if not isinstance(name, str) or not name.strip():
            raise ToolError("invalid_name", "name is required")
        normalized = nlu.normalize_phone(phone if isinstance(phone, str) else "")
        if not normalized:
            raise ToolError("invalid_phone", "phone must have ten digits")
        if not self.in_service_area(zip_code):
            raise ToolError("out_of_area", "zip is outside the service area", 422)

        with self._lock:
            if idempotency_key and idempotency_key in self._idempotency:
                return dict(self.bookings[self._idempotency[idempotency_key]])
            slot = next((s for s in self._all_slots() if s["slot_id"] == slot_id), None)
            if slot is None:
                raise ToolError("unknown_slot", "slot_id is not a bookable window", 404)
            if self._taken(slot_id) >= self.config.crews_per_window:
                raise ToolError("slot_unavailable", "that window is no longer open", 409)
            confirmation = f"BK-{len(self.bookings) + 1:04d}"
            booking = {
                "status": "booked",
                "confirmation": confirmation,
                "slot_id": slot_id,
                "slot_label": slot["label"],
                "job_type": job_type,
                "name": name.strip(),
                "phone": normalized,
                "zip": zip_code,
                "description": description or "",
            }
            self.bookings[confirmation] = booking
            if idempotency_key:
                self._idempotency[idempotency_key] = confirmation
            return dict(booking)

    def create_lead(
        self,
        reason: str,
        job_type: Optional[str] = None,
        description: str = "",
        name: Optional[str] = None,
        phone: Optional[str] = None,
        zip_code: Optional[str] = None,
        urgency: str = "normal",
        call_id: Optional[str] = None,
    ) -> dict:
        """Save a lead for the team to follow up on."""
        if reason not in LEAD_REASONS:
            raise ToolError("invalid_reason", "reason must be one of: " + ", ".join(sorted(LEAD_REASONS)))
        if job_type is not None:
            self._require_job(job_type)
        if zip_code is not None:
            self._require_zip(zip_code)
        if urgency not in ("normal", "urgent"):
            raise ToolError("invalid_urgency", "urgency must be normal or urgent")
        normalized = None
        if phone:
            normalized = nlu.normalize_phone(phone)
            if not normalized:
                raise ToolError("invalid_phone", "phone must have ten digits")
        with self._lock:
            lead = {
                "status": "created",
                "lead_id": f"LD-{len(self.leads) + 1:04d}",
                "reason": reason,
                "urgency": urgency,
                "job_type": job_type,
                "description": description or "",
                "name": name,
                "phone": normalized,
                "zip": zip_code,
                "call_id": call_id,
                "created_at": self.clock().isoformat(timespec="minutes"),
            }
            self.leads.append(lead)
            return dict(lead)
