import pytest

from receptionist import BusinessConfig, State, guardrails
from receptionist.states import TRANSITIONS, IllegalTransition, check_transition, mermaid

from conftest import OPEN_TIME, Harness

HAPPY = [
    "I have a leaky faucet",
    "00102",
    "the first one",
    "My name is Alex Sample",
    "yes",
    "yes please",
]


def test_happy_path_books_and_hangs_up(open_office):
    turns = open_office.call(HAPPY)
    session = open_office.session()
    assert session.outcome == "booked"
    assert session.path == [
        State.GREET, State.QUALIFY, State.SERVICE_AREA, State.OFFER_TIMES,
        State.CONTACT, State.BOOK, State.ENDED,
    ]
    assert turns[-1].ended and turns[-1].action.kind == "hangup"
    assert "BK-0001" in turns[-1].say
    booking = open_office.tools.bookings["BK-0001"]
    assert booking["slot_id"] == "2030-01-08T08:00"
    assert booking["name"] == "Alex Sample"
    assert booking["phone"] == "5555550142"
    assert not open_office.tools.leads


def test_greeting_discloses_the_assistant(open_office, closed_office):
    for harness in (open_office, closed_office):
        greeting = harness.call([])[0].say
        assert "automated assistant" in greeting
        assert "not a person" in greeting


def test_identity_question_gets_an_honest_answer_and_keeps_the_place(open_office):
    turns = open_office.call(["I have a leaky faucet", "wait, are you a real person?"])
    answer = turns[-1].say
    assert "automated assistant, not a person" in answer
    assert "ZIP code" in answer  # the pending question is asked again
    assert open_office.session().state is State.SERVICE_AREA
    assert open_office.session().retries == 0


def test_zip_given_with_the_job_skips_the_zip_question(open_office):
    turns = open_office.call(["my toilet is clogged, I'm in 00103"])
    assert open_office.session().state is State.OFFER_TIMES
    assert "arrival windows" in turns[-1].say


def test_out_of_area_ends_without_booking(open_office):
    turns = open_office.call(["the furnace is out", "00999"])
    session = open_office.session()
    assert session.outcome == "out_of_area"
    assert "outside our service area" in turns[-1].say
    assert not open_office.tools.bookings
    assert open_office.tools.leads[0]["reason"] == "out_of_area"


def test_request_for_a_human_transfers_with_a_lead(open_office):
    turns = open_office.call(["I have a leaky faucet", "let me talk to a person"])
    session = open_office.session()
    assert session.outcome == "handed_off"
    assert State.HANDOFF in session.path
    assert turns[-1].action.kind == "transfer"
    assert turns[-1].action.to == open_office.config.handoff_number
    lead = open_office.tools.leads[0]
    assert lead["reason"] == "caller_requested"
    assert lead["job_type"] == "plumbing"
    assert lead["phone"] == "5555550142"


def test_two_misses_in_qualify_hand_off(open_office):
    turns = open_office.call(["hmm", "it is hard to say"])
    assert "plumbing, electrical" in turns[1].say
    assert open_office.session().outcome == "handed_off"
    assert open_office.session().handoff_reason == "could_not_qualify"
    assert open_office.tools.leads[0]["description"] == "it is hard to say"


def test_silence_reprompts_then_hands_off(open_office):
    turns = open_office.call(["I have a leaky faucet", "", "   "])
    assert turns[2].say.startswith("Sorry, I didn't catch that.")
    assert "ZIP code" in turns[2].say
    assert open_office.session().outcome == "handed_off"
    assert open_office.session().handoff_reason == "no_input"


def test_none_of_those_offers_more_then_falls_back_to_callback(open_office):
    turns = open_office.call(
        ["I have a leaky faucet", "00102", "none of those", "none of those either",
         "Alex Sample", "yes"]
    )
    assert "next ones" in turns[3].say
    assert "team call you" in turns[4].say
    session = open_office.session()
    assert session.outcome == "callback_requested"
    assert State.BOOK not in session.path
    assert not open_office.tools.bookings
    assert open_office.tools.leads[0]["reason"] == "callback_requested"
    assert open_office.tools.leads[0]["name"] == "Alex Sample"


def test_saying_no_at_confirmation_goes_back_to_times(open_office):
    turns = open_office.call(HAPPY[:5] + ["no, wrong day", "the third one", "yes"])
    session = open_office.session()
    assert "open windows are" in turns[6].say
    assert session.path[-4:] == [State.OFFER_TIMES, State.CONTACT, State.BOOK, State.ENDED]
    # Name and phone were not asked for a second time.
    assert "Should I book it?" in turns[7].say
    assert open_office.tools.bookings["BK-0001"]["slot_id"] == "2030-01-08T13:00"


def test_slot_taken_between_offer_and_confirmation(open_office):
    open_office.call(HAPPY[:5])
    # Another caller books the same window before this one says yes.
    open_office.tools.book(
        "2030-01-08T08:00", job_type="hvac", name="Riley Testcase",
        phone="5555550155", zip_code="00101",
    )
    turn = open_office.receptionist.handle_utterance("c1", "yes")
    assert "just taken" in turn.say
    assert "between 8 and 10 AM" not in turn.say
    assert open_office.session().state is State.OFFER_TIMES
    open_office.receptionist.handle_utterance("c1", "the first one")
    open_office.receptionist.handle_utterance("c1", "yes")
    assert open_office.session().outcome == "booked"
    assert len(open_office.tools.bookings) == 2


def test_slot_taken_and_nothing_left_ends_with_a_callback():
    # One bookable day with a single window, so losing it leaves nothing.
    config = BusinessConfig(lookahead_days=1, weekday_window_starts=(8,))
    harness = Harness(OPEN_TIME, config)
    harness.call(HAPPY[:5])
    harness.tools.book(
        "2030-01-08T08:00", job_type="hvac", name="Riley Testcase",
        phone="5555550155", zip_code="00101",
    )
    turn = harness.receptionist.handle_utterance("c1", "yes")
    assert turn.ended
    assert harness.session().outcome == "callback_requested"
    assert harness.tools.leads[0]["name"] == "Alex Sample"


def test_no_openings_at_all_takes_a_callback():
    harness = Harness(OPEN_TIME, BusinessConfig(lookahead_days=0))
    turns = harness.call(["I have a leaky faucet", "00102", "Alex Sample", "yes"])
    assert "team call you" in turns[2].say
    assert harness.session().outcome == "callback_requested"
    assert State.OFFER_TIMES not in harness.session().path


def test_blocked_caller_id_asks_for_a_number(open_office):
    turns = open_office.call(
        ["I have a leaky faucet", "00102", "first", "Alex Sample", "uh", "555-555-0188", "yes"],
        caller="",
    )
    assert "best phone number" in turns[4].say
    assert "ten digit" in turns[5].say
    assert open_office.tools.bookings["BK-0001"]["phone"] == "5555550188"


def test_after_hours_takes_a_message_and_offers_no_times(closed_office):
    turns = closed_office.call(
        ["not an emergency, my dishwasher won't drain", "00103", "Jordan Example", "yes"]
    )
    session = closed_office.session()
    assert "office is closed" in turns[0].say
    assert session.outcome == "lead_captured"
    assert session.path == [
        State.GREET, State.AFTER_HOURS, State.SERVICE_AREA, State.CONTACT, State.ENDED,
    ]
    assert not closed_office.tools.bookings
    lead = closed_office.tools.leads[0]
    assert (lead["reason"], lead["job_type"], lead["zip"]) == ("after_hours", "appliance", "00103")
    assert "next business day" in turns[-1].say


def test_after_hours_bare_no_asks_for_the_message(closed_office):
    turns = closed_office.call(["no"])
    assert turns[-1].say == "Okay. What do you need help with?"
    assert closed_office.session().state is State.AFTER_HOURS


def test_after_hours_emergency_goes_to_the_on_call_line(closed_office):
    turns = closed_office.call(["emergency, a pipe burst"])
    session = closed_office.session()
    assert session.outcome == "emergency_transfer"
    assert turns[-1].action.to == closed_office.config.on_call_number
    assert "call 911" in turns[-1].say
    lead = closed_office.tools.leads[0]
    assert lead["urgency"] == "urgent" and lead["job_type"] == "plumbing"


def test_open_hours_emergency_goes_to_the_office(open_office):
    turns = open_office.call(["I smell gas near the furnace"])
    assert open_office.session().outcome == "emergency_transfer"
    assert turns[-1].action.to == open_office.config.handoff_number


def test_after_hours_request_for_a_human_cannot_transfer(closed_office):
    turns = closed_office.call(["can I speak to someone"])
    assert turns[-1].action.kind == "hangup"
    assert "office is closed" in turns[-1].say
    assert closed_office.session().outcome == "callback_requested"
    assert closed_office.tools.leads[0]["reason"] == "caller_requested"


def test_hangup_mid_call_saves_a_lead(open_office):
    open_office.call(["I have a leaky faucet", "00102"])
    session = open_office.receptionist.end_call("c1")
    assert session.outcome == "abandoned"
    assert session.state is State.ENDED
    assert open_office.tools.leads[0]["reason"] == "abandoned"


def test_hangup_before_saying_anything_saves_nothing(open_office):
    open_office.call([])
    assert open_office.receptionist.end_call("c1").outcome == "abandoned"
    assert not open_office.tools.leads


def test_end_call_after_a_finished_call_changes_nothing(open_office):
    open_office.call(HAPPY)
    assert open_office.receptionist.end_call("c1").outcome == "booked"
    assert open_office.receptionist.handle_utterance("c1", "hello?").ended


def test_calls_are_isolated_from_each_other(open_office):
    open_office.call(["I have a leaky faucet"], call_id="a")
    open_office.call(["the furnace is out", "00104"], call_id="b")
    assert open_office.session("a").state is State.SERVICE_AREA
    assert open_office.session("b").state is State.OFFER_TIMES
    assert open_office.session("a").job_type == "plumbing"


def test_every_line_spoken_passes_the_guardrail(open_office, closed_office):
    scripts = [HAPPY, ["hmm", "dunno"], ["are you a robot", "talk to a person"]]
    for harness in (open_office, closed_office):
        for index, script in enumerate(scripts):
            harness.call(script, call_id=f"g{index}")
            for kind, text in harness.session(f"g{index}").transcript:
                if kind == "assistant":
                    assert not guardrails.claims_to_be_human(text)


def test_transition_table_is_closed_and_every_state_is_reachable():
    assert set(TRANSITIONS) == set(State)
    reachable, frontier = {State.GREET}, [State.GREET]
    while frontier:
        for target in TRANSITIONS[frontier.pop()]:
            if target not in reachable:
                reachable.add(target)
                frontier.append(target)
    assert reachable == set(State)
    assert TRANSITIONS[State.ENDED] == frozenset()
    assert all(
        State.ENDED in targets for s, targets in TRANSITIONS.items() if s is not State.ENDED
    )


def test_illegal_transitions_are_refused(open_office):
    with pytest.raises(IllegalTransition):
        check_transition(State.GREET, State.BOOK)
    with pytest.raises(IllegalTransition):
        check_transition(State.ENDED, State.GREET)
    open_office.call([])
    with pytest.raises(IllegalTransition):
        open_office.receptionist._move(open_office.session(), State.BOOK)


def test_mermaid_export_lists_every_transition():
    diagram = mermaid()
    assert diagram.startswith("stateDiagram-v2")
    for state, targets in TRANSITIONS.items():
        for target in targets:
            assert f"{state.value} --> {target.value}" in diagram
