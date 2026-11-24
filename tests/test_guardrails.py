import pytest

from receptionist import guardrails, prompts

ALL_PROMPTS = {
    name: value
    for name, value in vars(prompts).items()
    if name.isupper() and isinstance(value, str)
}


def test_there_are_prompts_to_check():
    assert len(ALL_PROMPTS) > 20


@pytest.mark.parametrize("name", sorted(ALL_PROMPTS))
def test_no_prompt_claims_to_be_a_person(name):
    assert not guardrails.claims_to_be_human(ALL_PROMPTS[name])


@pytest.mark.parametrize("name", ["GREETING", "AFTER_HOURS_GREETING", "IDENTITY"])
def test_openers_and_identity_answer_disclose(name):
    assert guardrails.has_disclosure(ALL_PROMPTS[name])
    assert "not a person" in ALL_PROMPTS[name]


@pytest.mark.parametrize(
    "line",
    [
        "Yes, I'm a real person.",
        "I am a human, how can I help?",
        "I'm not a robot.",
        "Hi, my name is Sam from the office.",
        "You're speaking with a live person.",
        "This is a real person.",
    ],
)
def test_claims_to_be_human_are_caught(line):
    assert guardrails.claims_to_be_human(line)
    with pytest.raises(guardrails.GuardrailViolation):
        guardrails.enforce(line)


def test_first_turn_must_disclose():
    with pytest.raises(guardrails.GuardrailViolation):
        guardrails.enforce("Thanks for calling. How can I help?", first_turn=True)
    opener = "Thanks for calling. I'm the automated assistant, not a person."
    assert guardrails.enforce(opener, first_turn=True) == opener
    assert guardrails.enforce("What is the ZIP code?") == "What is the ZIP code?"
