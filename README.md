# Litmus Lab — L0 Support Training Simulation

A self-contained web application for training customer support analysts on
Litmus Edge L0 support skills. Trainees work through realistic simulated support
tickets — reading customer messages and screenshots, diagnosing issues, writing
remediation guides or escalation notes — and receive instant AI-generated feedback.

**No Zendesk account. No Docker. No live Litmus Edge instance. No external service
required beyond an Anthropic API key.**

---

## Table of Contents

1. [How It Works](#how-it-works)
2. [Repository Structure](#repository-structure)
3. [Prerequisites](#prerequisites)
4. [Setup](#setup)
5. [Running a Training Session](#running-a-training-session)
6. [Scenario Reference](#scenario-reference)
7. [How Grading Works](#how-grading-works)
8. [Adding New Scenarios](#adding-new-scenarios)
9. [Escalation vs. Resolution](#escalation-vs-resolution)
10. [Legacy Code](#legacy-code)

---

## How It Works

```
Trainer opens http://localhost:8000/new
  → Selects scenario + enters trainee name
  → Ticket created in local SQLite database

Trainee opens the ticket in their browser
  → Reads the customer's opening message and screenshots
  → Types replies to gather more information
    (customer replies immediately with scripted responses triggered by keywords)
  → Optionally marks as Escalation
  → Writes final response and clicks Solve

On Solve (takes ~2–3 seconds):
  → Full conversation sent to Claude with the scenario rubric
  → Claude returns score (0–100) and written feedback
  → Grade note appears on the ticket immediately

Trainer debriefs with the trainee using the grade note.
```

No background processes. No polling. No external accounts.

---

## Repository Structure

```
litmus-lab/
│
├── scenarios/                      ← Training scenario definitions
│   ├── le-s01-stopped-device.yaml
│   ├── le-s02-tagless-device.yaml
│   ├── le-s03-ssh-stopped.yaml
│   ├── le-s04-viewer-permissions.yaml
│   ├── le-s05-auth-service-crash.yaml  ← escalation scenario
│   ├── le-s06-data-corruption.yaml     ← escalation scenario
│   └── screenshots/                ← Pre-captured screenshots for each scenario
│       └── README.md               ← Which screenshots are needed and how to capture them
│
├── app/                            ← Application code
│   ├── main.py                     ← FastAPI app (routes, reply matching)
│   ├── database.py                 ← SQLite schema and CRUD helpers
│   ├── grader.py                   ← Claude API grading logic
│   └── templates/                  ← Jinja2 HTML templates
│       ├── base.html               ← Dark-themed master layout
│       ├── queue.html              ← Ticket list view
│       ├── new_ticket.html         ← Create ticket form (trainer)
│       └── ticket.html             ← Ticket conversation + grading view
│
├── scripts/
│   └── list_scenarios.py           ← List available scenarios with metadata
│
├── _legacy/                        ← Archived Phase 1/2/3 code (do not delete yet)
│   └── README.md                   ← Explains what was archived and why
│
├── .env.example                    ← Template for environment variables
├── requirements.txt                ← Python dependencies
└── README.md                       ← This file
```

---

## Prerequisites

- **Python 3.12+**
- **Anthropic API key** for Claude-based grading (only external dependency)
- **Screenshots** for each scenario (see `scenarios/screenshots/README.md`)

---

## Setup

**1. Install dependencies**

```bash
pip install -r requirements.txt
```

**2. Configure environment**

```bash
cp .env.example .env
```

Edit `.env`:

```bash
ANTHROPIC_API_KEY=sk-ant-your-key
```

**3. Start the server**

```bash
uvicorn app.main:app --reload
```

Open `http://localhost:8000`.

**4. (Optional) Add screenshots**

Follow `scenarios/screenshots/README.md` to capture or mock the required
screenshot files. Tickets work without screenshots but the diagnostic
experience is richer with them.

---

## Running a Training Session

### Step 1 — Create the ticket (Trainer)

Open `http://localhost:8000/new`, select a scenario, enter the trainee's name,
and click **Create Ticket**. Share the ticket URL with the trainee, or sit
together at the same machine.

### Step 2 — Trainee works the ticket

The trainee opens the ticket and sees:
- A message from a named customer at a named company
- Attached screenshots (clickable for full-size view)
- A diagnostic checklist in the sidebar

The trainee asks the customer clarifying questions by typing in the reply box.
**The customer replies immediately** — scripted responses triggered by keywords
in the trainee's comment.

Example:
> **Trainee:** Can you check what status the device shows in DeviceHub?
>
> **Customer (Carlos Mendes):** I just opened DeviceHub and found PLC-Line3.
> It has a red icon next to it — the status says "Stopped". Is that the problem?

If the trainee's comment doesn't match any scripted trigger, the customer replies
with a fallback "I need you to be more specific" response. This teaches trainees
to ask precise diagnostic questions.

### Step 3 — Trainee solves the ticket

Once the trainee has gathered enough information, they write their final response.

**If the issue is L0-fixable:** write a clear, step-by-step solution guide
addressed to the customer, then click **Solve Ticket**.

**If the issue requires engineering:** check **Mark as Escalation**, write an
escalation note with all relevant context, then click **Solve Ticket**.

Grading runs immediately (~2–3 seconds). The grade note appears on the ticket.

### Step 4 — Debrief

The grade note on the ticket shows:

```
LITMUS LAB — TRAINING GRADE
──────────────────────────────────────────────────
Trainee:         Jane Doe
Scenario:        le-s01 — Device stopped publishing data to MQTT
Expected action: RESOLVE

Score:           85/100  ✅ PASSED
Correct action:  ✅ Yes

KEY OBSERVATIONS:
  • Correctly identified the stopped device state from the screenshot
  • Provided accurate DeviceHub → Start instructions
  • Did not ask the customer to confirm data resumed after fix

TRAINER FEEDBACK:
  [2–3 paragraphs of specific written feedback]
──────────────────────────────────────────────────
```

---

## Scenario Reference

| ID | Title | Action | Difficulty |
|----|-------|--------|-----------|
| `le-s01` | Device stopped publishing data to MQTT | Resolve | Beginner |
| `le-s02` | New device created but no data in historian | Resolve | Beginner |
| `le-s03` | Remote SSH access not working | Resolve | Intermediate |
| `le-s04` | Engineer cannot modify device configuration | Resolve | Intermediate |
| `le-s05` | All users randomly logged out (auth crash) | **Escalate** | Intermediate |
| `le-s06` | Impossible sensor values after platform update | **Escalate** | Advanced |

**Suggested training order:** le-s01 → le-s02 → le-s03 → le-s04 → le-s05 → le-s06

Run the resolve scenarios first so trainees build confidence before encountering
the escalation scenarios.

---

## How Grading Works

When a ticket is solved, the app:

1. Collects the full public comment thread
2. Loads the scenario's `grading_rubric` field
3. Detects whether the Escalation checkbox was checked
4. Sends everything to `claude-haiku-4-5-20251001` with a structured grading prompt
5. Parses the JSON response into a `GradeResult`
6. Stores the score on the ticket (visible in the queue)
7. Posts the formatted grade note on the ticket

**Score breakdown (typical L0 scenario):**
- 50 pts — Correct root cause identified
- 25 pts — Accurate remediation/escalation steps
- 15 pts — Professional, clear communication
- 10 pts — Asked customer to verify the fix

**Passing threshold:** 70/100

**Critical penalties:**
- Escalating when the issue is L0-fixable: −40 pts
- NOT escalating when escalation is required: −50 pts (automatic ≤50 score cap)

Grading is non-deterministic (LLM output). Treat scores as guidance, not
objective measurements. The written feedback is more valuable than the number.

---

## Adding New Scenarios

Create a YAML file in `scenarios/` following this schema:

```yaml
id: le-s07                          # must be unique
title: Short descriptive title
difficulty: beginner | intermediate | advanced
expected_action: resolve | escalate

customer:
  name: Customer Name
  company: Company Name
  le_version: "4.0.6"

ticket:
  subject: "Email subject line the customer used"
  initial_message: |
    Multi-line message from the customer.
    Written in first person, realistic tone.

  attachments:                      # paths relative to scenarios/screenshots/
    - le-s07/screenshot1.png

diagnostic_checklist:
  - "Question 1 to prompt structured thinking"
  - "Question 2"
  - "Question 3"

root_cause: |
  Internal explanation of what's actually wrong.
  Not shown to trainee — used by grader only.

correct_response_summary: |         # for resolve scenarios
  1. Step one
  2. Step two

escalation_reason: |                # for escalation scenarios
  Why this cannot be fixed at L0.

grading_rubric: |
  Instructions for Claude when grading.
  Use point values (e.g. "CRITICAL (50 pts): ...").
  Score range: 0–100. Passing threshold: 70.

scripted_replies:
  - triggers: ["keyword1", "keyword2"]
    reply: |
      The customer's reply. Written in first person.

  - triggers: ["other keyword"]
    reply: |
      Another reply for a different line of questioning.

fallback_reply: |
  I'm not sure what you mean. Can you be more specific about what to check?
```

Then add screenshots to `scenarios/screenshots/le-s07/` and run
`python scripts/list_scenarios.py --verbose` to verify.

---

## Escalation vs. Resolution

Teaching trainees when to escalate is as important as teaching them how to
resolve issues. The escalation scenarios (le-s05, le-s06) are designed to
penalise incorrect resolution attempts.

**L0 support analysts should escalate when:**
- The issue is a platform bug requiring a software fix or firmware upgrade
- The issue requires appliance-level access beyond what the Litmus Edge UI exposes
- The issue involves data corruption or integrity risks
- No configuration change in the Litmus Edge UI can resolve it

---

## Legacy Code

The `_legacy/` directory contains retired code from three earlier phases:

- **Phase 1/2** — FastAPI app with live Litmus Edge SDK integration (broken-state
  scenarios trainee fixed directly inside LE)
- **Phase 3** — Zendesk-integrated approach (real Zendesk tickets, polling grader,
  Zendesk API dependency)

See [`_legacy/README.md`](_legacy/README.md) for full details.

**Do not delete `_legacy/` until this system is validated in production.**
