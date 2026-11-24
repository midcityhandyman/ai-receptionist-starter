"""Play scripted fake calls through the flow and print what happened.

    python -m receptionist.simulator                 all scenarios
    python -m receptionist.simulator scenarios/x.json  one or more files

Each scenario is a JSON file with a start time, a caller number, the
caller's lines, and the outcome we expect. The exit code is 1 when any
expectation fails, so the simulator doubles as a regression check.
"""

from __future__ import annotations

import json
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

from .config import BusinessConfig
from .flow import CallSession, Receptionist
from .providers import CallRunner, MockVoiceProvider
from .tools import ToolService

SCENARIO_DIR = Path(__file__).resolve().parent.parent / "scenarios"
WIDTH = 78


@dataclass
class ScenarioResult:
    name: str
    session: CallSession
    tools: ToolService
    provider: MockVoiceProvider
    failures: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def load_scenarios(paths: Optional[Sequence[str]] = None) -> List[dict]:
    files = [Path(p) for p in paths] if paths else sorted(SCENARIO_DIR.glob("*.json"))
    scenarios = []
    for path in files:
        with open(path, encoding="utf-8") as handle:
            scenarios.append(json.load(handle))
    return scenarios


def run_scenario(scenario: dict, business: Optional[BusinessConfig] = None) -> ScenarioResult:
    business = business or BusinessConfig()
    start = datetime.fromisoformat(scenario["start_time"])
    clock = lambda: start  # noqa: E731 - a frozen clock keeps runs repeatable
    tools = ToolService(business, clock)
    receptionist = Receptionist(business, tools, clock)
    provider = MockVoiceProvider()
    runner = CallRunner(receptionist, provider)
    call_id = "sim-" + scenario["name"]

    turn = runner.dispatch(
        {"type": "call.started", "call_id": call_id, "from": scenario.get("caller_number", "")}
    )
    for line in scenario["turns"]:
        if turn.ended:
            break
        turn = runner.dispatch({"type": "caller.utterance", "call_id": call_id, "text": line})
    if not turn.ended:
        runner.dispatch({"type": "call.ended", "call_id": call_id})

    session = receptionist.session(call_id)
    result = ScenarioResult(scenario["name"], session, tools, provider)
    result.failures = _check(scenario.get("expect", {}), result)
    return result


def _check(expect: dict, result: ScenarioResult) -> List[str]:
    session = result.session
    actual = {
        "outcome": session.outcome,
        "path": [s.value for s in session.path],
        "bookings": len(result.tools.bookings),
        "leads": len(result.tools.leads),
        "transfer_to": session.transfer_to,
        "lead_reason": session.lead["reason"] if session.lead else None,
    }
    failures = []
    for key, wanted in expect.items():
        if key not in actual:
            failures.append(f"unknown expectation key: {key}")
        elif actual[key] != wanted:
            failures.append(f"{key}: expected {wanted!r}, got {actual[key]!r}")
    return failures


def _wrap(label: str, text: str) -> str:
    prefix = f"  {label:<11}"
    return textwrap.fill(
        text, width=WIDTH, initial_indent=prefix, subsequent_indent=" " * len(prefix)
    )


def format_result(scenario: dict, result: ScenarioResult) -> str:
    session = result.session
    start = datetime.fromisoformat(scenario["start_time"])
    lines = [
        "=" * WIDTH,
        f"SCENARIO: {scenario['name']}",
        textwrap.fill(scenario.get("description", ""), width=WIDTH),
        f"Call time: {start.strftime('%A %Y-%m-%d %H:%M')} "
        f"({'after hours' if session.after_hours else 'office open'})",
        f"Caller ID: {scenario.get('caller_number') or '(blocked)'}",
        "-" * WIDTH,
    ]
    labels = {"assistant": "ASSISTANT:", "caller": "CALLER:"}
    for kind, text in session.events:
        if kind in labels:
            lines.append(_wrap(labels[kind], text))
        else:
            lines.append(f"      [{kind}] {text}")
    summary = session.summary()
    lines += [
        "-" * WIDTH,
        f"OUTCOME: {summary['outcome']}",
        f"  path:         {' > '.join(summary['path'])}",
        f"  confirmation: {summary['confirmation'] or 'none'}",
        f"  lead:         {summary['lead_id'] or 'none'}"
        + (f" (reason: {session.lead['reason']})" if session.lead else ""),
        f"  transfer to:  {summary['transfer_to'] or 'none'}",
        "  expectations: " + ("PASS" if result.passed else "FAIL"),
    ]
    lines += [f"    - {failure}" for failure in result.failures]
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    scenarios = load_scenarios(argv or None)
    if not scenarios:
        print("no scenarios found")
        return 1
    results = []
    for scenario in scenarios:
        result = run_scenario(scenario)
        results.append(result)
        print(format_result(scenario, result))
        print()
    print("=" * WIDTH)
    print("SUMMARY")
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"  {status}  {result.name:<32} {result.session.outcome}")
    failed = sum(1 for r in results if not r.passed)
    print(f"{len(results) - failed} of {len(results)} scenarios met their expectations")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
