# Litmus Lab — L0 Support Training via Zendesk

A training system for customer support analysts learning to handle Litmus Edge
support tickets. Trainees work entirely within Zendesk — reading realistic
customer tickets, diagnosing issues from screenshots, writing remediation guides
or escalation notes — and receive AI-generated feedback scored against a rubric.

**No live Litmus Edge instance required. No Docker. No web server.**

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
Trainer runs:
  python scripts/create_ticket.py le-s01 trainee@company.com
          │
          ▼
  Zendesk ticket created with:
  - Realistic customer persona and symptom description
  - Screenshots showing the problem (attached)
  - Diagnostic checklist to prompt structured thinking

Trainee works in Zendesk:
  - Reads the ticket and screenshots
  - Diagnoses the root cause
  - Either writes a resolution guide for the customer,
    or applies the 'escalate' tag and writes an escalation note
  - Marks the ticket as Solved

Grader runs (background):
  python scripts/grade_tickets.py
          │
          ▼
  Detects solved training tickets (polls every 60s)
  → Sends full thread to Claude with the scenario rubric
  → Claude returns score (0–100) and written feedback
  → Posted as internal note on the Zendesk ticket
```

The trainer reviews the internal note after each session. No other infrastructure
is required beyond Zendesk and an Anthropic API key.

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
├── scripts/                        ← Trainer CLI tools
│   ├── create_ticket.py            ← Create a Zendesk ticket for a trainee
│   ├── grade_tickets.py            ← Poll for solved tickets and grade them
│   └── list_scenarios.py           ← List available scenarios
│
├── app/                            ← Shared library modules
│   ├── zendesk_client.py           ← Zendesk REST API wrapper
│   └── grader.py                   ← Claude API grading logic
│
├── _legacy/                        ← Archived Phase 1/2 code (do not delete yet)
│   └── README.md                   ← Explains what was archived and why
│
├── .env.example                    ← Template for environment variables
├── requirements.txt                ← Python dependencies
└── README.md                       ← This file
```

---

## Prerequisites

- **Python 3.12+**
- **Zendesk account** with admin access:
  - A dedicated service account email (e.g. `litmus-lab@yourcompany.com`)
  - An API token for that account
  - Trainee user accounts already created in Zendesk
- **Anthropic API key** for Claude-based grading
- **Screenshots** for each scenario (see `scenarios/screenshots/README.md`)

---

## Setup

**1. Clone the repo and install dependencies**

```bash
git clone https://github.com/amirkhadem123/litmus-edge-training-lab.git
cd litmus-edge-training-lab
git checkout feature/zendesk-l0-training
pip install -r requirements.txt
```

**2. Configure environment variables**

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```bash
ZENDESK_SUBDOMAIN=yourcompany      # yourcompany.zendesk.com
ZENDESK_EMAIL=litmus-lab@yourcompany.com
ZENDESK_API_TOKEN=your-api-token
ANTHROPIC_API_KEY=sk-ant-your-key
```

To generate a Zendesk API token:
> Zendesk Admin Center → Apps & Integrations → APIs → Zendesk API → Token Access → Add API token

**3. Verify scenarios load correctly**

```bash
python scripts/list_scenarios.py --verbose
```

Expected output: 6 scenarios listed, with screenshot status for each.

**4. Add screenshots**

Follow the instructions in `scenarios/screenshots/README.md` to capture or mock
the required screenshot files. Scenarios work without screenshots (the ticket
body will still be created) but the diagnostic experience is significantly richer
with them.

---

## Running a Training Session

### Step 1 — Create the ticket

```bash
python scripts/create_ticket.py <scenario-id> <trainee-email>

# Examples:
python scripts/create_ticket.py le-s01 jane.doe@company.com
python scripts/create_ticket.py le-s05 john.smith@company.com
```

The script prints the Zendesk ticket URL when done. Send it to the trainee, or
let them find it in their Zendesk queue.

### Step 2 — Trainee works the ticket

The trainee logs into Zendesk and opens the assigned ticket. They will see:
- A message from a named customer at a named company
- A symptom description
- Attached screenshots
- A short diagnostic checklist to prompt structured thinking before responding

The trainee investigates by asking the customer clarifying questions as ticket
comments. **The poller (running in step 3) replies automatically as the customer**
within 60 seconds, using pre-written responses triggered by keywords in the
trainee's comment. This creates a realistic back-and-forth conversation.

For example:
> **Trainee:** Can you check what status the device shows in DeviceHub?
> *(60 seconds later)*
> **Customer (Carlos Mendes):** I just opened DeviceHub and found PLC-Line3.
> It has a red icon next to it — the status says "Stopped". Is that the problem?

If the trainee's comment doesn't match any scripted trigger, the customer replies
with a generic "I need you to be more specific" response (if a `fallback_reply`
is defined in the scenario). This teaches trainees to ask precise questions.

Once the trainee has enough information, they write their final response.

**If the issue is L0-fixable:** they write a clear, step-by-step solution guide
addressed to the customer and mark the ticket **Solved**.

**If the issue requires engineering:** they apply the `escalate` tag, write an
escalation note with all relevant context, and mark the ticket **Solved**.

> **Note on the 'escalate' tag:** In Zendesk, tags are editable in the ticket
> sidebar. The trainee types `escalate` in the Tags field before solving.
> This is the signal the grader uses to detect the trainee's chosen action.

### Step 3 — Grade the ticket

Start the grader (can run before or during the session — it only processes
solved tickets):

```bash
python scripts/grade_tickets.py          # runs continuously, polls every 60s
python scripts/grade_tickets.py --once   # grade pending tickets once and exit
```

When the trainee marks their ticket Solved, the grader detects it within 60
seconds, sends the full thread to Claude, and posts a grading note on the ticket.

### Step 4 — Debrief

Open the ticket in Zendesk as an agent and scroll to the internal note at the
bottom. It shows:

```
🎓 LITMUS LAB — TRAINING GRADE
──────────────────────────────────────────────────
Trainee:         jane.doe@company.com
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

Use the note as the basis for a debrief conversation with the trainee.

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

Run the resolve scenarios first so trainees build confidence and understand what
L0 *can* fix before encountering the escalation scenarios.

---

## How Grading Works

When a ticket is solved, the grader:

1. Extracts the scenario ID from the ticket tags (e.g. `scenario-le-s01`)
2. Loads the corresponding YAML file and its `grading_rubric` field
3. Fetches all public comments from the ticket thread
4. Detects whether the `escalate` tag was applied
5. Sends everything to `claude-haiku-4-5` with a structured grading prompt
6. Parses the JSON response into a `GradeResult`
7. Posts a formatted internal note and applies the `litmus-lab-graded` tag

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
    - le-s07/screenshot2.png

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
  3. Step three

escalation_reason: |                # for escalation scenarios
  Why this cannot be fixed at L0.

grading_rubric: |
  Instructions for Claude when grading.
  Use point values (e.g. "CRITICAL (50 pts): ...").
  Specify exact deductions for critical failures.
  Score range: 0–100. Passing threshold: 70.

# Scripted replies — triggered by keywords in the trainee's comments.
# First matching entry wins. Replies are posted as the ticket requester.
scripted_replies:
  - triggers: ["keyword1", "keyword2"]  # any of these (case-insensitive) in comment
    reply: |
      The customer's reply text. Written in first person from the customer's
      perspective. Can be multi-line.

  - triggers: ["other keyword"]
    reply: |
      Another customer reply for a different line of questioning.

# Optional: sent when no trigger matches. Teaches trainees to ask precisely.
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

**Common mistakes the scenarios test for:**
- Escalating a simple device start/stop issue visible in a screenshot (le-s01, le-s03)
- Attempting to fix a firmware integer overflow by changing tag data types (le-s06)
- Telling a customer to restart a system service when they cannot do so from the UI (le-s05)

---

## Legacy Code

The `_legacy/` directory contains the original Phase 1 and Phase 2 Litmus Lab
application — a FastAPI web app with live Litmus Edge SDK integration.

See [`_legacy/README.md`](_legacy/README.md) for a full explanation of what was
there, why it was retired, and how the scenario knowledge was preserved in the
new YAML format.

**Do not delete `_legacy/` until the Zendesk-based system is validated in production.**
