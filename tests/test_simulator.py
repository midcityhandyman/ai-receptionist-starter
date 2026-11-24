import json
from pathlib import Path

import pytest

from receptionist import guardrails, simulator

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = simulator.load_scenarios()


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
    for scenario in SCENARIOS:
        number = scenario.get("caller_number", "")
        assert number == "" or number.startswith("+155555501")


def test_saved_demo_output_matches_a_fresh_simulator_run(capsys):
    simulator.main([])
    fresh = capsys.readouterr().out.strip().splitlines()
    saved = (ROOT / "demo" / "output.txt").read_text(encoding="utf-8").splitlines()
    assert saved[: len(fresh)] == fresh
