from datetime import datetime

import pytest

from receptionist import BusinessConfig, ToolError, ToolService

MONDAY = datetime(2030, 1, 7, 10, 15)
GOOD = dict(job_type="plumbing", name="Alex Sample", phone="555-555-0142", zip_code="00102")


@pytest.fixture
def tools():
    return ToolService(BusinessConfig(), lambda: MONDAY)


def test_availability_starts_tomorrow_and_is_sorted(tools):
    slots = tools.availability("plumbing", "00102", limit=10)["slots"]
    ids = [s["slot_id"] for s in slots]
    assert ids[0] == "2030-01-08T08:00"
    assert ids == sorted(ids)
    assert slots[0]["label"] == "Tuesday, January 8, between 8 and 10 AM"
    assert slots[1]["label"] == "Tuesday, January 8, between 10 AM and 12 PM"


def test_availability_skips_sunday_and_uses_saturday_hours():
    friday = datetime(2030, 1, 11, 9, 0)
    tools = ToolService(BusinessConfig(), lambda: friday)
    ids = [s["slot_id"] for s in tools.availability("hvac", "00101", limit=10)["slots"]]
    assert ids[:2] == ["2030-01-12T09:00", "2030-01-12T11:00"]
    assert not any(i.startswith("2030-01-13") for i in ids)
    assert ids[2] == "2030-01-14T08:00"


def test_availability_out_of_area_returns_no_slots(tools):
    assert tools.availability("plumbing", "00999") == {"in_service_area": False, "slots": []}


def test_availability_pages_with_after(tools):
    first = tools.availability("plumbing", "00102", limit=3)["slots"]
    second = tools.availability("plumbing", "00102", limit=3, after=first[-1]["slot_id"])["slots"]
    assert second[0]["slot_id"] > first[-1]["slot_id"]
    assert not {s["slot_id"] for s in first} & {s["slot_id"] for s in second}


def test_book_removes_the_slot_from_availability(tools):
    booking = tools.book("2030-01-08T08:00", **GOOD)
    assert booking["confirmation"] == "BK-0001"
    assert booking["phone"] == "5555550142"
    ids = [s["slot_id"] for s in tools.availability("plumbing", "00102", limit=10)["slots"]]
    assert "2030-01-08T08:00" not in ids


def test_double_booking_is_rejected(tools):
    tools.book("2030-01-08T08:00", **GOOD)
    with pytest.raises(ToolError) as info:
        tools.book("2030-01-08T08:00", **dict(GOOD, name="Riley Testcase"))
    assert info.value.code == "slot_unavailable"
    assert info.value.status == 409
    assert len(tools.bookings) == 1


def test_two_crews_allow_two_bookings_per_window():
    tools = ToolService(BusinessConfig(crews_per_window=2), lambda: MONDAY)
    tools.book("2030-01-08T08:00", **GOOD)
    tools.book("2030-01-08T08:00", **dict(GOOD, name="Riley Testcase"))
    with pytest.raises(ToolError):
        tools.book("2030-01-08T08:00", **dict(GOOD, name="Casey Placeholder"))


def test_book_is_idempotent_with_a_key(tools):
    first = tools.book("2030-01-08T08:00", idempotency_key="k1", **GOOD)
    again = tools.book("2030-01-08T08:00", idempotency_key="k1", **GOOD)
    assert first == again
    assert len(tools.bookings) == 1


@pytest.mark.parametrize(
    "override, code",
    [
        ({"phone": "555-0142"}, "invalid_phone"),
        ({"name": "   "}, "invalid_name"),
        ({"zip_code": "102"}, "invalid_zip"),
        ({"zip_code": "00999"}, "out_of_area"),
        ({"job_type": "roofing"}, "invalid_job_type"),
    ],
)
def test_book_validation(tools, override, code):
    with pytest.raises(ToolError) as info:
        tools.book("2030-01-08T08:00", **dict(GOOD, **override))
    assert info.value.code == code
    assert not tools.bookings


@pytest.mark.parametrize(
    "slot_id", ["2030-01-07T10:00", "2030-01-13T08:00", "2030-01-08T09:00", "nope"]
)
def test_book_rejects_slots_that_are_not_bookable(tools, slot_id):
    # Same day, a Sunday, an off-grid hour, and garbage.
    with pytest.raises(ToolError) as info:
        tools.book(slot_id, **GOOD)
    assert info.value.code == "unknown_slot"


def test_create_lead_minimal_and_full(tools):
    bare = tools.create_lead("could_not_qualify")
    assert bare["lead_id"] == "LD-0001" and bare["phone"] is None
    full = tools.create_lead(
        "after_hours", job_type="hvac", description="no heat", name="Jordan Example",
        phone="(555) 555-0177", zip_code="00103", urgency="urgent", call_id="c9",
    )
    assert full["lead_id"] == "LD-0002"
    assert full["phone"] == "5555550177"
    assert full["created_at"] == "2030-01-07T10:15"
    assert len(tools.leads) == 2


@pytest.mark.parametrize(
    "kwargs, code",
    [
        ({"reason": "because"}, "invalid_reason"),
        ({"reason": "other", "phone": "12"}, "invalid_phone"),
        ({"reason": "other", "urgency": "extreme"}, "invalid_urgency"),
        ({"reason": "other", "job_type": "roofing"}, "invalid_job_type"),
    ],
)
def test_create_lead_validation(tools, kwargs, code):
    with pytest.raises(ToolError) as info:
        tools.create_lead(**kwargs)
    assert info.value.code == code
    assert not tools.leads


@pytest.mark.parametrize(
    "when, expected",
    [
        (datetime(2030, 1, 7, 7, 59), False),
        (datetime(2030, 1, 7, 8, 0), True),
        (datetime(2030, 1, 7, 16, 59), True),
        (datetime(2030, 1, 7, 17, 0), False),
        (datetime(2030, 1, 12, 10, 0), True),   # Saturday morning
        (datetime(2030, 1, 12, 14, 0), False),  # Saturday afternoon
        (datetime(2030, 1, 13, 10, 0), False),  # Sunday
    ],
)
def test_business_hours(when, expected):
    assert BusinessConfig().is_open(when) is expected
