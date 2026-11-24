"""Configuration for the business and for the runtime.

Everything here is synthetic. The ZIP codes are deliberately unassigned
values and the phone numbers sit in the reserved 555-01xx range.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Optional, Tuple

JOB_TYPES = {
    "appliance": "appliance repair",
    "plumbing": "plumbing",
    "electrical": "electrical",
    "hvac": "heating and cooling",
    "handyman": "handyman",
}


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class BusinessConfig:
    """Facts about the company the assistant answers for."""

    company_name: str = "Example Home Services"
    service_zips: frozenset = frozenset({"00101", "00102", "00103", "00104"})
    weekday_hours: Tuple[int, int] = (8, 17)
    saturday_hours: Optional[Tuple[int, int]] = (9, 13)
    weekday_window_starts: Tuple[int, ...] = (8, 10, 13, 15)
    saturday_window_starts: Tuple[int, ...] = (9, 11)
    window_hours: int = 2
    lookahead_days: int = 6
    crews_per_window: int = 1
    handoff_number: str = "+15555550100"
    on_call_number: str = "+15555550199"
    max_retries: int = 2

    def is_open(self, now: datetime) -> bool:
        """True when a human can take a transferred call."""
        weekday = now.weekday()
        if weekday <= 4:
            hours = self.weekday_hours
        elif weekday == 5:
            hours = self.saturday_hours
        else:
            hours = None
        if hours is None:
            return False
        return hours[0] <= now.hour < hours[1]

    def window_starts_for(self, weekday: int) -> Tuple[int, ...]:
        if weekday <= 4:
            return self.weekday_window_starts
        if weekday == 5 and self.saturday_hours is not None:
            return self.saturday_window_starts
        return ()

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "BusinessConfig":
        env = os.environ if env is None else env
        defaults = cls()
        zips = env.get("SERVICE_ZIPS", "")
        service_zips = (
            frozenset(z.strip() for z in zips.split(",") if z.strip())
            if zips
            else defaults.service_zips
        )
        return cls(
            company_name=env.get("COMPANY_NAME", defaults.company_name),
            service_zips=service_zips,
            handoff_number=env.get("HANDOFF_NUMBER", defaults.handoff_number),
            on_call_number=env.get("ON_CALL_NUMBER", defaults.on_call_number),
        )


@dataclass(frozen=True)
class RuntimeConfig:
    """Settings for the HTTP server and the voice provider."""

    voice_provider: str = "mock"
    voice_api_key: str = ""
    voice_api_base_url: str = "https://voice.example.com/v1"
    tool_shared_secret: str = ""
    host: str = "127.0.0.1"
    port: int = 8080

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "RuntimeConfig":
        env = os.environ if env is None else env
        defaults = cls()
        try:
            port = int(env.get("PORT", defaults.port))
        except ValueError as exc:
            raise ConfigError("PORT must be an integer") from exc
        return cls(
            voice_provider=env.get("VOICE_PROVIDER", defaults.voice_provider).lower(),
            voice_api_key=env.get("VOICE_API_KEY", ""),
            voice_api_base_url=env.get("VOICE_API_BASE_URL", defaults.voice_api_base_url),
            tool_shared_secret=env.get("TOOL_SHARED_SECRET", ""),
            host=env.get("HOST", defaults.host),
            port=port,
        )
