"""Every line the assistant can say.

Keeping the wording in one module makes it easy to review, and lets the
guardrail tests scan all of it for anything that sounds like a claim to
be a person.
"""

GREETING = (
    "Thanks for calling {company}. I'm the automated assistant, not a person. "
    "I can book a service visit or get you to someone on the team."
)
ASK_JOB = "What can we help you with today?"

AFTER_HOURS_GREETING = (
    "Thanks for calling {company}. I'm the automated assistant, not a person. "
    "The office is closed right now, but I can take a message for a callback "
    "on the next business day. If this is an emergency, say emergency."
)
ASK_AFTER_HOURS = "What do you need help with?"

IDENTITY = (
    "I'm an automated assistant, not a person. "
    "If you would rather talk with someone on the team, just say so."
)

DID_NOT_CATCH = "Sorry, I didn't catch that."

QUALIFY_RETRY = (
    "I can help with plumbing, electrical, heating and cooling, "
    "appliance repair, and general handyman work."
)
ASK_JOB_RETRY = "Which of those is closest to what you need?"
JOB_ACK = "Got it, that sounds like {job} work."
MESSAGE_ACK = "Okay, I'll note that for the team."

ASK_ZIP = "What is the five digit ZIP code where the work is needed?"
ZIP_RETRY = "I need the ZIP code as five digits."
OUT_OF_AREA = (
    "I'm sorry, ZIP code {zip} is outside our service area, so I can't book "
    "a visit there. Thanks for calling {company}. Goodbye."
)

OFFER_INTRO = "Good news, we cover that area. I have these arrival windows open: {slots}."
OFFER_MORE = "Here are the next ones: {slots}."
OFFER_AGAIN = "No problem. The open windows are: {slots}."
SLOT_TAKEN = "I'm sorry, that window was just taken. Here is what is open now: {slots}."
ASK_SLOT = "Which works best? You can also say none of those."
NO_SLOTS = (
    "I don't have a window that fits, so I'll have the team call you to "
    "find a time."
)

ASK_NAME = "Can I get your name?"
NAME_RETRY = "Sorry, I missed the name."
ASK_NAME_AGAIN = "What name should I put on this?"
NAME_ACK = "Thanks, {name}."
CONFIRM_PHONE = "Is {phone} the best number to reach you?"
ASK_PHONE = "What is the best phone number to reach you, with area code?"
PHONE_RETRY = "I need a ten digit phone number."

CONFIRM_BOOKING = (
    "To confirm: a {job} visit, arriving {slot}, in ZIP code {zip}, under the "
    "name {name}. Should I book it?"
)
BOOKED = (
    "You're booked. Your confirmation number is {confirmation}. A technician "
    "will arrive {slot}. Thanks for calling {company}. Goodbye."
)
BOOK_UNCLEAR = "I didn't catch a yes or no."

LEAD_CAPTURED = (
    "Thanks, {name}. I've passed this along and someone from the team will "
    "call you back on the next business day. Goodbye."
)
CALLBACK_REQUESTED = (
    "Thanks, {name}. I've passed this along and someone from the team will "
    "call you back shortly to find a time. Goodbye."
)

HANDOFF = "Sure, I'll connect you with someone on the team now. Please hold."
HANDOFF_STUCK = (
    "I'm having trouble with that, so I'll connect you with someone on the "
    "team who can help. Please hold."
)
HANDOFF_CLOSED = (
    "The office is closed, so I can't connect you right now. I've left a "
    "note for the team to call you back on the next business day. Goodbye."
)
EMERGENCY = (
    "If anyone is in danger, or you smell gas, hang up and call 911. "
    "I'm connecting you with our {target} now. Please stay on the line."
)
