import pytest

from receptionist import nlu

SLOTS = [
    {"slot_id": "2030-01-08T15:00", "start": "2030-01-08T15:00:00"},
    {"slot_id": "2030-01-09T08:00", "start": "2030-01-09T08:00:00"},
    {"slot_id": "2030-01-09T10:00", "start": "2030-01-09T10:00:00"},
]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("I have a leaky faucet", "plumbing"),
        ("my water heater is leaking", "plumbing"),
        ("the furnace won't turn on", "hvac"),
        ("we have no heat", "hvac"),
        ("an outlet is dead", "electrical"),
        ("the dishwasher is leaking", "appliance"),
        ("need some drywall patched", "handyman"),
        ("it is hard to explain", None),
    ],
)
def test_job_type(text, expected):
    assert nlu.job_type(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("00102", "00102"),
        ("It's 00102.", "00102"),
        ("zero zero one oh two", "00102"),
        ("call me at 555-555-0142", None),
        ("I don't know", None),
    ],
)
def test_extract_zip(text, expected):
    assert nlu.extract_zip(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("555-555-0142", "5555550142"),
        ("+1 (555) 555-0142", "5555550142"),
        ("it's five five five 555 0142", "5555550142"),
        ("555-0142", None),
    ],
)
def test_extract_phone(text, expected):
    assert nlu.extract_phone(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("My name is Alex Sample", "Alex Sample"),
        ("this is jordan example calling about a leak", "Jordan Example"),
        ("Casey Placeholder", "Casey Placeholder"),
        ("yes", None),
        ("what do you mean by that exactly", None),
        ("555-555-0142", None),
    ],
)
def test_extract_name(text, expected):
    assert nlu.extract_name(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("yes please", True),
        ("that works", True),
        ("no", False),
        ("no, that's not right", False),
        ("purple", None),
    ],
)
def test_yes_no(text, expected):
    assert nlu.yes_no(text) is expected


@pytest.mark.parametrize(
    "text",
    [
        "are you a real person?",
        "Am I talking to a robot",
        "is this a recording?",
        "wait, are you human",
    ],
)
def test_identity_question(text):
    assert nlu.is_identity_question(text)


@pytest.mark.parametrize(
    "text",
    [
        "can I talk to a real person",
        "I'd like to speak with someone",
        "transfer me to the office",
        "representative",
        "get me a human",
    ],
)
def test_wants_human(text):
    assert nlu.wants_human(text)


@pytest.mark.parametrize(
    "text",
    [
        "can you get someone to fix my leaky faucet",
        "a person broke my fence",
        "my office door sticks",
    ],
)
def test_job_descriptions_are_not_handoff_requests(text):
    assert not nlu.wants_human(text)


def test_emergency_and_its_negation():
    assert nlu.is_emergency("this is an emergency")
    assert nlu.is_emergency("I smell gas in the kitchen")
    assert nlu.is_emergency("the basement is flooding")
    assert not nlu.is_emergency("it's not an emergency, my sink drips")
    assert not nlu.is_emergency("my faucet drips")


@pytest.mark.parametrize(
    "text, expected",
    [
        ("the first one", 0),
        ("second", 1),
        ("the last one", 2),
        ("option 3", 2),
        ("2", 1),
        ("Wednesday morning", 1),
        ("Tuesday", 0),
        ("the afternoon one", 0),
        ("Wednesday at 10", 2),
        ("10 am", 2),
        ("3 pm", 0),
        ("none of those", nlu.NONE_OF_THESE),
        ("no", nlu.NONE_OF_THESE),
        ("do you have anything later", nlu.NONE_OF_THESE),
        ("Friday", None),
        ("um", None),
    ],
)
def test_pick_slot(text, expected):
    assert nlu.pick_slot(text, SLOTS) == expected
