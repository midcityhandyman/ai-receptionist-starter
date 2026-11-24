# ai-receptionist-starter

**An AI phone receptionist for home service companies (plumbing, electrical, HVAC, handyman).**

When everyone is out on a job, the phone goes to voicemail, and a missed call is usually a lost job. This project is the working core of an assistant that answers instead. On each call it:

- **Answers and says what it is.** Every call opens with "I'm the automated assistant, not a person." It never pretends to be a human.
- **Qualifies the job.** What is wrong, and is the job in your service area.
- **Books the visit.** Offers open arrival windows, takes a name and callback number, reads it back and books.
- **Hands off cleanly.** If the caller asks for a person, has an emergency, or the assistant cannot follow, it transfers the call and saves what the caller already said, so nobody has to ask twice. After hours it takes a message.

**What this is and is not.** This is a starter: the call logic, the booking tools and a test harness. It is not connected to a phone line. No real voice provider is wired in, there is no audio, and the calendar is an in-memory stand-in. Calls are simulated as text against a mock provider, which is how every path below can be run and checked on a laptop with no accounts or keys. Going live means connecting a voice platform and a real calendar; see [Limitations](#limitations).

## What you will see

One of the eight simulated calls, copied from [`demo/output.txt`](demo/output.txt) (captured output of `python demo/run_demo.py`). The caller is scripted, the company and the caller are made up, and the bracketed lines show what the software did behind the conversation.

```text
SCENARIO: happy_path_booking
Open hours. Caller with a leaky faucet in the service area books the second
window offered.
Call time: Monday 2030-01-07 10:15 (office open)
Caller ID: +15555550142
------------------------------------------------------------------------------
      [state] greet -> qualify
  ASSISTANT: Thanks for calling Example Home Services. I'm the automated
             assistant, not a person. I can book a service visit or get you to
             someone on the team. What can we help you with today?
  CALLER:    Hi, I have a leaky faucet in my kitchen
      [state] qualify -> service_area
  ASSISTANT: Got it, that sounds like plumbing work. What is the five digit
             ZIP code where the work is needed?
  CALLER:    It's 00102
      [tool] availability {"job_type": "plumbing", "zip_code": "00102", "limit": 3} -> 3 open windows
      [state] service_area -> offer_times
  ASSISTANT: Good news, we cover that area. I have these arrival windows open:
             Tuesday, January 8, between 8 and 10 AM; Tuesday, January 8,
             between 10 AM and 12 PM; Tuesday, January 8, between 1 and 3 PM.
             Which works best? You can also say none of those.
  CALLER:    The second one works
      [state] offer_times -> contact
  ASSISTANT: Tuesday, January 8, between 10 AM and 12 PM, got it. Can I get
             your name?
  CALLER:    My name is Alex Sample
  ASSISTANT: Thanks, Alex Sample. Is 555-555-0142 the best number to reach
             you?
  CALLER:    Yes it is
      [state] contact -> book
  ASSISTANT: To confirm: a plumbing visit, arriving Tuesday, January 8,
             between 10 AM and 12 PM, in ZIP code 00102, under the name Alex
             Sample. Should I book it?
  CALLER:    Yes please
      [tool] book {"slot_id": "2030-01-08T10:00", "job_type": "plumbing", "name": "Alex Sample", "phone": "5555550142", "zip_code": "00102", "description": "Hi, I have a leaky faucet in my kitchen", "idempotency_key": "sim-happy_path_booking:2030-01-08T10:00"} -> booked BK-0001
      [state] book -> ended
  ASSISTANT: You're booked. Your confirmation number is BK-0001. A technician
             will arrive Tuesday, January 8, between 10 AM and 12 PM. Thanks
             for calling Example Home Services. Goodbye.
      [action] hangup
------------------------------------------------------------------------------
OUTCOME: booked
  path:         greet > qualify > service_area > offer_times > contact > book > ended
  confirmation: BK-0001
  lead:         none
  transfer to:  none
  expectations: PASS
```

The other seven calls end differently: out of the service area, a request for a person, an after hours message, an after hours emergency, "are you a real person?", a caller the assistant cannot understand, and a hang up part way through.

## How it is built

Most "AI receptionist" demos are one long prompt, which makes them hard to test and easy to derail. This one is built the other way around, so a call can be tested like any other code.

- **Call flow as a state machine.** Greet, qualify the job, check the service area, offer arrival windows, collect contact details, book, hand off to a human, and a separate after hours path. Every allowed transition is listed in one table in `receptionist/states.py`, and the engine refuses any move that is not in it.
- **Three tools.** `availability`, `book` and `create_lead`, usable in process or over HTTP as endpoints a voice platform calls. Booking is idempotent and rejects double bookings.
- **Voice provider adapter.** A small `VoiceProvider` contract with two implementations: a mock that records everything (the default, no key needed), and a generic HTTP adapter whose API shape is an invented example, not a real vendor's.
- **Call simulator.** Scripted fake calls in `scenarios/*.json` are played through the real flow. It prints the transcript, every state change, every tool call and the outcome, and exits non-zero if a call does not end the way the scenario expects.
- **Identity guardrail.** The first line of every call must contain the disclosure. Any line that matches a "claims to be a person" pattern raises an error before it is spoken. Asking "are you a real person?" gets a straight answer in any state, then the call carries on where it was.
- **Sensible escalation.** Two misses in a row in any state and the assistant stops guessing and hands off. An emergency goes straight to a transfer. Every handoff, hang up and dead end leaves a lead behind with whatever was collected.

## Architecture

```mermaid
flowchart LR
    caller([Caller]) <--> platform[Voice platform<br/>speech to text, text to speech]
    platform -- "call events" --> server[server.py<br/>HTTP endpoints]
    platform -. "tool calls" .-> server
    server --> adapter[providers<br/>mock or http adapter]
    adapter --> runner[CallRunner]
    runner --> flow[flow.py<br/>state machine engine]
    flow --> states[(states.py<br/>transition table)]
    flow --> nlu[nlu.py<br/>rule based understanding]
    flow --> guard[guardrails.py<br/>identity rules]
    flow --> tools[tools.py<br/>availability, book, create_lead]
    server --> tools
    sim[simulator.py<br/>scripted calls] --> adapter
    scenarios[(scenarios/*.json)] --> sim
```

The call flow itself, generated from the transition table by `mermaid()` in `receptionist/states.py`:

```mermaid
stateDiagram-v2
    [*] --> greet
    greet --> qualify
    greet --> after_hours
    greet --> ended
    qualify --> service_area
    qualify --> handoff
    qualify --> ended
    after_hours --> service_area
    after_hours --> handoff
    after_hours --> ended
    service_area --> offer_times
    service_area --> contact
    service_area --> handoff
    service_area --> ended
    offer_times --> contact
    offer_times --> handoff
    offer_times --> ended
    contact --> book
    contact --> handoff
    contact --> ended
    book --> offer_times
    book --> handoff
    book --> ended
    handoff --> ended
    ended --> [*]
```

| State | What happens | Leaves when |
| --- | --- | --- |
| `greet` | Discloses the assistant, routes on business hours | Always, immediately |
| `qualify` | Works out the job type | Job recognised, or two misses (handoff) |
| `after_hours` | Office closed: take a message, or escalate an emergency | Message given |
| `service_area` | Checks the ZIP code | In area, or out of area (call ends, lead saved) |
| `offer_times` | Offers three arrival windows, then three more | Window picked, or nothing fits (callback request) |
| `contact` | Name and callback number | Both collected |
| `book` | Reads the booking back and books on a yes | Booked, or the window was taken (back to offers) |
| `handoff` | Saves a lead, transfers if anyone can answer | Always, immediately |
| `ended` | Terminal | Never |

## Run it

Python 3.10 or newer. There are no runtime dependencies, so after cloning this works with nothing installed:

```bash
python -m receptionist.simulator
```

That plays all eight scripted calls. To play one, pass its file: `python -m receptionist.simulator scenarios/01_happy_path_booking.json`.

To start the HTTP endpoints on `127.0.0.1:8080` with the mock provider:

```bash
python -m receptionist.server
curl http://127.0.0.1:8080/health
```

The server uses the real clock, so the windows it offers are real upcoming dates. The simulator and demo use fixed dates in 2030 so their output never changes.

## Run the tests

The only thing to install is pytest. A virtual environment inside the folder is fine:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m pytest
```

206 tests, a few seconds, no network and no keys. They cover the language rules, the tools, every path through the flow (including a window being taken between the offer and the confirmation), the guardrail, both provider adapters, the HTTP layer over a real local socket, and every scenario. CI runs the same tests plus the demo on Python 3.10 and 3.12 (`.github/workflows/ci.yml`).

## Demo

```bash
python demo/run_demo.py
```

This runs every scenario through the simulator, then calls the tool handlers directly (the same ones the HTTP server exposes). The captured output is in [`demo/output.txt`](demo/output.txt), and a test fails if that file drifts from what the simulator prints. A handoff from it:

```text
  CALLER:    I need an outlet replaced in the garage
      [state] qualify -> service_area
  ASSISTANT: Got it, that sounds like electrical work. What is the five digit
             ZIP code where the work is needed?
  CALLER:    Actually, can I just talk to a real person?
      [state] service_area -> handoff
      [tool] create_lead {"reason": "caller_requested", "job_type": "electrical", "description": "I need an outlet replaced in the garage", "phone": "5555550144", "urgency": "normal"} -> lead LD-0001
      [state] handoff -> ended
  ASSISTANT: Sure, I'll connect you with someone on the team now. Please hold.
      [action] transfer to +15555550100
------------------------------------------------------------------------------
OUTCOME: handed_off
```

"Transfer" here means the mock provider recorded a transfer instruction. No call is placed.

## HTTP endpoints

| Method and path | Purpose |
| --- | --- |
| `GET /health` | Liveness check, no auth |
| `POST /tools/availability` | `{"job_type", "zip", "limit"?, "after"?}` returns open arrival windows |
| `POST /tools/book` | `{"slot_id", "job_type", "name", "phone", "zip", "description"?, "idempotency_key"?}` |
| `POST /tools/create-lead` | `{"reason", "job_type"?, "description"?, "name"?, "phone"?, "zip"?, "urgency"?, "call_id"?}` |
| `POST /voice/events` | Call started, caller utterance and call ended events, answered by the state machine |

There are two ways to use this with a voice platform. Either the platform sends each transcribed caller turn to `/voice/events` and speaks whatever comes back, so the state machine is in charge. Or the platform runs its own conversation and only calls the three `/tools/*` endpoints. The tests exercise both over HTTP. With the mock provider, a call event looks like `{"type": "call.started", "call_id": "c1", "from": "+15555550142"}`, then `{"type": "caller.utterance", "call_id": "c1", "text": "..."}`, then `{"type": "call.ended", "call_id": "c1"}`.

Errors come back as `{"error": "<code>", "message": "..."}` with a matching status: 400 for bad input, 401 for a missing or wrong secret, 404 for an unknown window or call, 409 when a window was just taken, 422 when booking a ZIP outside the service area (`availability` answers that case with 200 and `"in_service_area": false`).

## Configuration

Copy `.env.example` to `.env` and export it in your shell. Everything is optional; with nothing set you get the mock provider and the synthetic defaults.

| Variable | Default | Meaning |
| --- | --- | --- |
| `VOICE_PROVIDER` | `mock` | `mock` or `http` |
| `VOICE_API_KEY` | empty | Required only when `VOICE_PROVIDER=http` |
| `VOICE_API_BASE_URL` | `https://voice.example.com/v1` | Base URL of the platform's control API |
| `TOOL_SHARED_SECRET` | empty | When set, every POST must send it as `X-Tool-Secret` |
| `COMPANY_NAME` | `Example Home Services` | Name used in the greeting |
| `SERVICE_ZIPS` | `00101,00102,00103,00104` | Comma separated ZIP codes served |
| `HANDOFF_NUMBER`, `ON_CALL_NUMBER` | 555-01xx numbers | Where transfers go |
| `HOST`, `PORT` | `127.0.0.1`, `8080` | Where the server listens |

Business hours, arrival windows and crew capacity are fields on `BusinessConfig` in `receptionist/config.py`.

## Layout

```text
receptionist/
  states.py       State enum and the transition table
  flow.py         Engine: one handler per state, handoff, retries, call log
  nlu.py          Rule based understanding of caller utterances
  prompts.py      Every line the assistant can say
  guardrails.py   Identity rules enforced on every outgoing line
  tools.py        availability, book, create_lead with an in-memory store
  server.py       HTTP endpoints (standard library)
  simulator.py    Plays scripted calls and checks their outcomes
  providers/      VoiceProvider contract, mock, generic HTTP adapter, CallRunner
scenarios/        Scripted fake calls as JSON
demo/             Demo script and its captured output
tests/            pytest suite
```

## Where this pattern runs

This starter is drawn from systems that run two small service companies day to day, where an assistant answers the phone, books what it safely can and passes everything else to a person with the details already written down. The parts that mattered most there are the parts kept here: a flow you can read as a table, a hard rule about saying what the assistant is, and a handoff that never drops what the caller already said. All names, numbers, ZIP codes and wording in this repository are synthetic.

## Limitations

- **The language understanding is keyword rules.** It is deterministic and testable, and it will miss plenty of real phrasing. A caller who says "the thing under the sink is dripping" is fine; one who describes a problem without any of the known words gets handed off after two tries. In production you would replace the functions in `nlu.py` with a model call and keep the state machine.
- **No real voice provider is wired in, and there is no audio.** Nothing here has answered a real phone call. This starts at text. Speech to text, text to speech, barge in and latency are the voice platform's job and are not simulated.
- **The HTTP provider is a generic example.** Its payload and endpoint shapes are invented, not any vendor's API. It is tested only against a fake transport. Connecting a real platform means writing an adapter for that platform's actual webhooks.
- **The identity guardrail is a pattern check.** It is airtight for the fixed lines in `prompts.py`, which is all the assistant can say today. If you let a model write the replies, it becomes a backstop that catches the listed phrasings, not a guarantee.
- **Storage is in memory.** Bookings, leads and call sessions vanish on restart and are not shared between processes. A real deployment needs a database and a calendar or dispatch system behind `tools.py`.
- **Scheduling is simplified.** Fixed two hour windows, one shared capacity number, no per trade crews, no travel time, no same day slots, no holidays.
- **Time is naive local time.** There is no timezone handling.
- **Shared secret auth only.** There is no webhook signature check, rate limit or TLS; put it behind a proxy that does those.
- **US formats only.** Five digit ZIP codes and ten digit phone numbers, English only.
- **The emergency list is short and not safety reviewed.** It routes to a transfer and reads a 911 line; it is not a substitute for a real emergency policy.
- **Not load tested.** The server is the standard library threading server, fine for a demo and for tests.

License: MIT, see the LICENSE file.
