"""Small rule based language understanding for caller utterances.

This is intentionally simple and deterministic so the whole flow can be
tested offline. A production build would swap these functions for a
model call while keeping the same return types.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional, Sequence

# Order matters: on a tie the earlier job type wins.
JOB_KEYWORDS = {
    "appliance": [
        "dishwasher", "washer", "washing machine", "dryer", "fridge",
        "refrigerator", "oven", "stove", "appliance", "garbage disposal",
    ],
    "plumbing": [
        "leak", "leaky", "faucet", "toilet", "drain", "clog", "clogged",
        "pipe", "water heater", "plumbing", "plumber", "sink", "sewer",
    ],
    "electrical": [
        "outlet", "breaker", "wiring", "light fixture", "electrical",
        "electrician", "light switch", "panel", "ceiling fan",
    ],
    "hvac": [
        "furnace", "air conditioner", "air conditioning", "ac", "heat",
        "thermostat", "hvac", "cooling", "boiler", "heat pump",
    ],
    "handyman": [
        "drywall", "door", "paint", "shelf", "shelves", "fence", "deck",
        "handyman", "gutter", "tile", "caulk", "cabinet",
    ],
}

_DIGIT_WORDS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

NONE_OF_THESE = -1

_IDENTITY_RE = re.compile(
    r"\b(are you|is this|am i (talking|speaking) (to|with))\b.*"
    r"\b(real|human|person|robot|bot|machine|ai|computer|recording|automated)\b",
    re.IGNORECASE,
)
_PEOPLE = (
    r"(human|person|someone|somebody|representative|operator|agent|manager|"
    r"dispatcher|team|staff|office)"
)
_HUMAN_RE = re.compile(
    rf"\b(speak|talk)\b.{{0,20}}\b(to|with)\b.{{0,15}}\b{_PEOPLE}\b"
    rf"|\b(transfer|connect)\b.{{0,30}}\b{_PEOPLE}\b"
    r"|\b(get|give) me (a |an |the )?(real |live )?"
    r"(human|person|representative|operator|agent|manager)\b"
    r"|^\W*(representative|operator|human|agent|real person)\W*(please)?\W*$",
    re.IGNORECASE,
)
_EMERGENCY_RE = re.compile(
    r"\b(emergency|gas leak|smell(s|ing)? (of )?gas|flooding|flooded|burst pipe|"
    r"pipe burst|sparks?|sparking|smoke|carbon monoxide)\b",
    re.IGNORECASE,
)
_NOT_EMERGENCY_RE = re.compile(
    r"\b(not|no|isn't|is not|non)[ -]?(really )?(an? )?emergency\b", re.IGNORECASE
)
_NO_RE = re.compile(
    r"\b(no|nope|nah|not|don't|do not|wrong|incorrect)\b", re.IGNORECASE
)
_YES_RE = re.compile(
    r"\b(yes|yeah|yep|yup|correct|sure|right|ok|okay|please do|go ahead|"
    r"sounds good|that works|perfect|book it)\b",
    re.IGNORECASE,
)
_NONE_RE = re.compile(
    r"\b(none|neither|different|another|other (day|time)s?|later|something else)\b",
    re.IGNORECASE,
)
_NAME_LEAD_RE = re.compile(
    r"\b(?:my name is|name's|name is|this is|it's|it is|i am|i'm|call me)\s+(.+)",
    re.IGNORECASE,
)
_NOT_NAMES = {
    "yes", "no", "what", "why", "um", "uh", "hello", "hi", "the", "a", "not",
    "sure", "okay", "ok", "sorry", "huh", "pardon",
}


def is_identity_question(text: str) -> bool:
    """Caller asks whether they are talking to a person or a machine."""
    return bool(_IDENTITY_RE.search(text))


def wants_human(text: str) -> bool:
    return bool(_HUMAN_RE.search(text))


def is_emergency(text: str) -> bool:
    cleaned = _NOT_EMERGENCY_RE.sub(" ", text)
    return bool(_EMERGENCY_RE.search(cleaned))


def strip_emergency_negation(text: str) -> str:
    return _NOT_EMERGENCY_RE.sub(" ", text).strip(" ,.")


def yes_no(text: str) -> Optional[bool]:
    """True for yes, False for no, None when unclear. No wins a tie."""
    if _NO_RE.search(text):
        return False
    if _YES_RE.search(text):
        return True
    return None


def job_type(text: str) -> Optional[str]:
    """Best matching job type, or None when nothing matches."""
    lowered = text.lower()
    best, best_score = None, 0
    for job, keywords in JOB_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            if re.search(rf"\b{re.escape(keyword)}(s|ing|ed)?\b", lowered):
                score += len(keyword.split())
        if score > best_score:
            best, best_score = job, score
    return best


def _digit_runs(text: str) -> List[str]:
    """Runs of digits, joining spoken digits such as 'zero zero one'."""
    runs: List[str] = []
    current = ""
    for token in re.findall(r"[A-Za-z]+|\d+|[^\sA-Za-z\d]", text.lower()):
        if token.isdigit():
            current += token
        elif token in _DIGIT_WORDS:
            current += _DIGIT_WORDS[token]
        elif token in "-().+" and current:
            continue
        else:
            if current:
                runs.append(current)
            current = ""
    if current:
        runs.append(current)
    return runs


def extract_zip(text: str) -> Optional[str]:
    for run in _digit_runs(text):
        if len(run) == 5:
            return run
    return None


def normalize_phone(value: str) -> Optional[str]:
    """Ten digit phone number, or None."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else None


def extract_phone(text: str) -> Optional[str]:
    for run in _digit_runs(text):
        phone = normalize_phone(run)
        if phone:
            return phone
    return None


def format_phone(phone: str) -> str:
    return f"{phone[0:3]}-{phone[3:6]}-{phone[6:]}"


def extract_name(text: str) -> Optional[str]:
    match = _NAME_LEAD_RE.search(text)
    candidate = match.group(1) if match else text
    candidate = re.split(r"[,.!?]| and | calling ", candidate)[0]
    if re.search(r"\d", candidate):
        return None
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", candidate)
    if not words or len(words) > 4:
        return None
    if not match and len(words) > 3:
        return None
    if any(w.lower() in _NOT_NAMES for w in words):
        return None
    return " ".join(w.capitalize() for w in words)


def _ordinal(text: str, count: int) -> Optional[int]:
    lowered = text.lower()
    words = [
        (r"\b(first|1st)\b", 0),
        (r"\b(second|2nd)\b", 1),
        (r"\b(third|3rd)\b", 2),
        (r"\b(last)\b", count - 1),
    ]
    for pattern, index in words:
        if re.search(pattern, lowered) and 0 <= index < count:
            return index
    match = re.fullmatch(r"\W*(?:option|number)?\s*(one|two|three|[1-3])\W*", lowered)
    if match:
        token = match.group(1)
        index = int(_DIGIT_WORDS.get(token, token)) - 1
        if index < count:
            return index
    return None


def _spoken_hour(text: str) -> Optional[int]:
    match = re.search(r"\b(\d{1,2})(?::00)?\s*(a\.?m\.?|p\.?m\.?|o'?clock)", text.lower())
    meridiem = match.group(2) if match else ""
    if not match:
        match = re.search(r"\bat (\d{1,2})\b", text.lower())
    if not match:
        return None
    hour = int(match.group(1))
    if meridiem.startswith("p") and hour < 12:
        hour += 12
    elif not meridiem.startswith("a") and hour < 8:
        hour += 12
    return hour


def pick_slot(text: str, slots: Sequence[dict]) -> Optional[int]:
    """Index of the offered slot the caller chose.

    Returns NONE_OF_THESE when the caller rejects all of them and None
    when the answer could not be understood.
    """
    if not slots:
        return None
    index = _ordinal(text, len(slots))
    if index is not None:
        return index

    lowered = text.lower()
    candidates = list(range(len(slots)))
    starts = [datetime.fromisoformat(s["start"]) for s in slots]
    filtered = False

    for number, name in enumerate(_WEEKDAYS):
        if name in lowered:
            candidates = [i for i in candidates if starts[i].weekday() == number]
            filtered = True
            break
    if "morning" in lowered:
        candidates = [i for i in candidates if starts[i].hour < 12]
        filtered = True
    elif "afternoon" in lowered:
        candidates = [i for i in candidates if starts[i].hour >= 12]
        filtered = True
    hour = _spoken_hour(text)
    if hour is not None:
        candidates = [i for i in candidates if starts[i].hour == hour]
        filtered = True

    if filtered and candidates:
        return candidates[0]
    if _NONE_RE.search(lowered) or (not filtered and yes_no(text) is False):
        return NONE_OF_THESE
    return None
