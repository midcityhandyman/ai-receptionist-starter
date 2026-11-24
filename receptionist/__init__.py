"""Voice AI receptionist starter for a home services company.

The package has no required dependencies. The main pieces are:

- states: the call flow as an explicit state machine
- flow: the engine that walks a call through those states
- understanding: what the caller said, from keyword rules (default) or
  from Claude (claude_understander, optional, needs the anthropic SDK)
- tools: availability, booking and lead capture
- server: HTTP endpoints a voice platform calls
- providers: voice provider adapters, including an offline mock
- vapi_tools: the tools in Vapi's custom tool format (from its docs)
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

__version__ = "0.2.0"
