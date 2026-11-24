from datetime import datetime

import pytest

from receptionist import BusinessConfig, Receptionist, ToolService

OPEN_TIME = datetime(2030, 1, 7, 10, 15)  # a Monday morning
CLOSED_TIME = datetime(2030, 1, 7, 21, 30)  # the same Monday, late evening
CALLER = "+15555550142"


class Harness:
    """A receptionist with a clock the test controls."""

    def __init__(self, now: datetime, config: BusinessConfig = None, understander=None):
        self.now = now
        self.config = config or BusinessConfig()
        self.tools = ToolService(self.config, lambda: self.now)
        self.receptionist = Receptionist(
            self.config, self.tools, lambda: self.now, understander
        )

    def call(self, lines, call_id="c1", caller=CALLER):
        """Start a call, say each line, return the list of turns."""
        turns = [self.receptionist.start_call(call_id, caller)]
        for line in lines:
            turns.append(self.receptionist.handle_utterance(call_id, line))
        return turns

    def session(self, call_id="c1"):
        return self.receptionist.session(call_id)


@pytest.fixture
def open_office():
    return Harness(OPEN_TIME)


@pytest.fixture
def closed_office():
    return Harness(CLOSED_TIME)
