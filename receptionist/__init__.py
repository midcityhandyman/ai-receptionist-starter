"""Voice AI receptionist starter for a home services company.

The package is dependency free. The main pieces are:

- states: the call flow as an explicit state machine
- flow: the engine that walks a call through those states
- tools: availability, booking and lead capture
- server: HTTP endpoints a voice platform calls
- providers: voice provider adapters, including an offline mock
- simulator: scripted fake calls that print transcripts and outcomes
"""

from .config import BusinessConfig, RuntimeConfig
from .flow import Action, CallSession, Receptionist, Turn
from .states import State
from .tools import ToolError, ToolService

__all__ = [
    "Action",
    "BusinessConfig",
    "CallSession",
    "Receptionist",
    "RuntimeConfig",
    "State",
    "ToolError",
    "ToolService",
    "Turn",
]

__version__ = "0.1.0"
