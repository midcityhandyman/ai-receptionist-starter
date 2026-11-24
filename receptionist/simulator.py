"""Play scripted fake calls through the flow and print what happened.

    python -m receptionist.simulator                 all scenarios
    python -m receptionist.simulator scenarios/x.json  one or more files
    python -m receptionist.simulator --understanding recorded
    python -m receptionist.simulator --understanding claude

Each scenario is a JSON file with a start time, a caller number, the
caller's lines, and the outcome we expect. The exit code is 1 when any
expectation fails, so the simulator doubles as a regression check.

--understanding picks how caller lines are understood:

    keyword   the rules in nlu.py (default, offline, no key)
    recorded  the Claude code path, fed hand written replies stored in
              scenarios/model_path/*.json by a fake client. Offline.
    claude    the real model through the Anthropic SDK. Needs the SDK
              and credentials, sends caller lines to the API, and its
              output can differ from run to run.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

from .config import BusinessConfig, ConfigError
from .flow import CallSession, Receptionist
from .providers import CallRunner, MockVoiceProvider
from .tools import ToolService
from .understanding import CLAUDE, KEYWORD, Understander, get_understander

SCENARIO_DIR = Path(__file__).resolve().parent.parent / "scenarios"
MODEL_SCENARIO_DIR = SCENARIO_DIR / "model_path"
RECORDED = "recorded"
MODES = (KEYWORD, RECORDED, CLAUDE)
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


def default_files(mode: str = KEYWORD) -> List[Path]:
    """Scenario files a mode plays when none are named."""
    plain = sorted(SCENARIO_DIR.glob("*.json"))
    model = sorted(MODEL_SCENARIO_DIR.glob("*.json"))
    return {KEYWORD: plain, RECORDED: model, CLAUDE: plain + model}[mode]


def load_scenarios(paths: Optional[Sequence[str]] = None, mode: str = KEYWORD) -> List[dict]:
    files = [Path(p) for p in paths] if paths else default_files(mode)
    scenarios = []
    for path in files:
        with open(path, encoding="utf-8") as handle:
            scenarios.append(json.load(handle))
    return scenarios


def _recorded_understander(scenario: dict):
    """The Claude code path with a fake client replaying the scenario's replies."""
    from .claude_understander import ClaudeUnderstander, RecordedClient, reply

    entries = scenario.get("recorded_model_replies")
    if entries is None:
        raise ValueError(f"scenario {scenario['name']!r} has no recorded_model_replies")
    if len(entries) != len(scenario["turns"]):
        raise ValueError(
            f"scenario {scenario['name']!r} needs one recorded reply (or null) per turn"
        )
    # A plain entry lists only the fields that are not at their empty value.
    expanded = [
        entry if entry is None or any(key.startswith("_") for key in entry) else reply(**entry)
        for entry in entries
    ]
    client = RecordedClient(expanded)
    return ClaudeUnderstander(client=client), client


def run_scenario(
    scenario: dict,
    business: Optional[BusinessConfig] = None,
    mode: str = KEYWORD,
    understander: Optional[Understander] = None,
) -> ScenarioResult:
    business = business or BusinessConfig()
    start = datetime.fromisoformat(scenario["start_time"])
    clock = lambda: start  # noqa: E731 - a frozen clock keeps runs repeatable
    tools = ToolService(business, clock)
    recorded_client = None
    if understander is None and mode == RECORDED:
        understander, recorded_client = _recorded_understander(scenario)
    elif understander is None:
        understander = get_understander(mode)
    receptionist = Receptionist(business, tools, clock, understander)
    provider = MockVoiceProvider()
    runner = CallRunner(receptionist, provider)
    call_id = "sim-" + scenario["name"]

    turn = runner.dispatch(
        {"type": "call.started", "call_id": call_id, "from": scenario.get("caller_number", "")}
    )
    for index, line in enumerate(scenario["turns"]):
        if turn.ended:
            break
        if recorded_client is not None:
            recorded_client.position = index
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
        "model_turns": session.model_turns,
        "fallbacks": list(session.fallbacks),
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
    ]
    if session.model_turns or session.fallbacks:
        lines.append(
            f"  understanding: model on {session.model_turns} caller turns, "
            f"keyword fallback on {len(session.fallbacks)}"
            + (f" ({', '.join(session.fallbacks)})" if session.fallbacks else "")
        )
    lines += [
        "  expectations: " + ("PASS" if result.passed else "FAIL"),
    ]
    lines += [f"    - {failure}" for failure in result.failures]
    return "\n".join(lines)


_MODE_BANNER = {
    RECORDED: "recorded (Claude code path, hand written replies from a fake client, offline)",
    CLAUDE: "claude (live model through the Anthropic SDK)",
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m receptionist.simulator", description="Play scripted fake calls."
    )
    parser.add_argument("files", nargs="*", help="scenario files (default: all for the mode)")
    parser.add_argument(
        "--understanding", choices=MODES, default=KEYWORD,
        help="how caller lines are understood (default: keyword, offline)",
    )
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    mode = args.understanding
    scenarios = load_scenarios(args.files or None, mode)
    if not scenarios:
        print("no scenarios found")
        return 1
    # One live client for the whole run, so the cached system prompt is reused.
    try:
        shared = get_understander(CLAUDE) if mode == CLAUDE else None
    except ConfigError as exc:
        print(f"cannot use --understanding claude: {exc}")
        return 2
    if mode != KEYWORD:
        print(f"Understanding backend: {_MODE_BANNER[mode]}")
        print()
    results = []
    for scenario in scenarios:
        result = run_scenario(scenario, mode=mode, understander=shared)
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
