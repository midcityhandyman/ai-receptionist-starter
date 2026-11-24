import json
import sys
from pathlib import Path

import pytest

from receptionist import guardrails, simulator

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = simulator.load_scenarios()
MODEL_SCENARIOS = simulator.load_scenarios(mode=simulator.RECORDED)


def test_scenarios_exist_and_have_unique_names():
    names = [s["name"] for s in SCENARIOS]
    assert len(names) >= 8
    assert len(set(names)) == len(names)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s["name"])
def test_scenario_meets_its_expectations(scenario):
    result = simulator.run_scenario(scenario)
    assert scenario["expect"], "every scenario must state an expected outcome"
    assert result.failures == []
    spoken = result.provider.spoken("sim-" + scenario["name"])
    assert guardrails.has_disclosure(spoken[0])
    assert not any(guardrails.claims_to_be_human(line) for line in spoken)


def test_scenarios_cover_every_outcome():
    outcomes = {simulator.run_scenario(s).session.outcome for s in SCENARIOS}
    assert outcomes >= {
        "booked", "out_of_area", "handed_off", "lead_captured",
        "emergency_transfer", "abandoned",
    }


def test_a_wrong_expectation_fails_the_run(tmp_path, capsys):
    scenario = dict(SCENARIOS[0], expect={"outcome": "handed_off", "typo_key": 1})
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(scenario), encoding="utf-8")
    assert simulator.main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "expected 'handed_off', got 'booked'" in out
    assert "unknown expectation key: typo_key" in out


def test_full_run_prints_transcripts_and_passes(capsys):
    assert simulator.main([]) == 0
    out = capsys.readouterr().out
    assert "ASSISTANT:" in out and "CALLER:" in out and "OUTCOME: booked" in out
    assert f"{len(SCENARIOS)} of {len(SCENARIOS)} scenarios met their expectations" in out


def test_scenario_data_is_obviously_fake():
    for scenario in SCENARIOS + MODEL_SCENARIOS:
        number = scenario.get("caller_number", "")
        assert number == "" or number.startswith("+155555501")


def test_saved_demo_output_matches_a_fresh_simulator_run(capsys):
    simulator.main([])
    fresh = capsys.readouterr().out.strip().splitlines()
    saved = (ROOT / "demo" / "output.txt").read_text(encoding="utf-8").splitlines()
    assert saved[: len(fresh)] == fresh


# ----- the model path, with recorded replies from a fake client -----


def test_default_run_is_keyword_and_does_not_touch_the_model_path():
    assert [s["name"] for s in simulator.load_scenarios()] == [s["name"] for s in SCENARIOS]
    assert not any("recorded_model_replies" in s for s in SCENARIOS)
    assert all(simulator.run_scenario(s).session.model_turns == 0 for s in SCENARIOS)


def test_model_path_scenarios_exist():
    names = [s["name"] for s in MODEL_SCENARIOS]
    assert len(names) >= 4 and len(set(names)) == len(names)
    assert not set(names) & {s["name"] for s in SCENARIOS}


@pytest.mark.parametrize("scenario", MODEL_SCENARIOS, ids=lambda s: s["name"])
def test_model_path_scenario_meets_its_expectations(scenario):
    result = simulator.run_scenario(scenario, mode=simulator.RECORDED)
    assert "model_turns" in scenario["expect"] and "fallbacks" in scenario["expect"]
    assert result.failures == []
    spoken = result.provider.spoken("sim-" + scenario["name"])
    assert guardrails.has_disclosure(spoken[0])
    assert not any(guardrails.claims_to_be_human(line) for line in spoken)


def test_paraphrase_scenario_needs_the_model_path():
    """The same caller lines through keyword rules alone end in a handoff."""
    scenario = next(s for s in MODEL_SCENARIOS if s["name"] == "model_paraphrase_booking")
    assert simulator.run_scenario(scenario, mode=simulator.RECORDED).session.outcome == "booked"
    by_rules = simulator.run_scenario(scenario, mode=simulator.KEYWORD).session
    assert by_rules.outcome == "handed_off" and by_rules.model_turns == 0


def test_fallback_scenario_covers_every_failure_kind_and_still_books():
    scenario = next(s for s in MODEL_SCENARIOS if s["name"] == "model_fallback_to_keyword_rules")
    session = simulator.run_scenario(scenario, mode=simulator.RECORDED).session
    assert session.outcome == "booked"
    assert session.fallbacks == ["timeout", "schema_mismatch", "refusal", "low_confidence"]


def test_recorded_mode_requires_one_reply_per_turn():
    scenario = dict(MODEL_SCENARIOS[0], recorded_model_replies=[{"intent": "answer_yes"}])
    with pytest.raises(ValueError):
        simulator.run_scenario(scenario, mode=simulator.RECORDED)
    with pytest.raises(ValueError):
        simulator.run_scenario(SCENARIOS[0], mode=simulator.RECORDED)


def test_recorded_flag_runs_the_model_path_scenarios(capsys):
    assert simulator.main(["--understanding", "recorded"]) == 0
    out = capsys.readouterr().out
    assert "Understanding backend: recorded" in out
    assert "[understanding] model: intent=service_request job_type=plumbing" in out
    assert "[understanding] keyword rules (model fallback: timeout)" in out
    assert f"{len(MODEL_SCENARIOS)} of {len(MODEL_SCENARIOS)} scenarios met their expectations" in out


def test_claude_flag_without_the_sdk_exits_cleanly(capsys, monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    assert simulator.main(["--understanding", "claude"]) == 2
    assert "pip install anthropic" in capsys.readouterr().out


def test_saved_demo_output_includes_the_model_path_run(capsys):
    simulator.main(["--understanding", "recorded"])
    fresh = capsys.readouterr().out.strip()
    saved = (ROOT / "demo" / "output.txt").read_text(encoding="utf-8")
    assert fresh in saved
    assert chr(8212) not in saved
