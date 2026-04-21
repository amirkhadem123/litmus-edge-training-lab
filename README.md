# Litmus Lab — L0 Support Training Simulation

A self-contained web application for training customer support analysts on
Litmus Edge L0 support skills. Trainees work through realistic simulated
support tickets — reading customer messages and screenshots, diagnosing issues,
writing remediation guides or escalation notes — and receive instant AI-generated
feedback.

**No Zendesk. No live Litmus Edge instance. One internal API endpoint for
everything.**

---

## Table of Contents

1. [How It Works](#how-it-works)
2. [Repository Structure](#repository-structure)
3. [Prerequisites](#prerequisites)
4. [Local Setup (Dev)](#local-setup-dev)
5. [Production Deployment (Docker)](#production-deployment-docker)
6. [Cloudflare Access Integration](#cloudflare-access-integration)
7. [Running a Training Session](#running-a-training-session)
8. [Scenario Reference](#scenario-reference)
9. [How Grading Works](#how-grading-works)
10. [Adding New Scenarios](#adding-new-scenarios)
11. [Escalation vs. Resolution](#escalation-vs-resolution)
12. [Architecture](#architecture)
13. [Legacy Code](#legacy-code)

---

## How It Works

```
Trainer opens /new  →  selects scenario + enters trainee name  →  ticket created

Trainee opens the ticket
  → Reads the customer's opening message and screenshots
  → Types replies to gather more information
      (AI plays the customer, constrained by the scenario YAML)
  → Optionally marks as Escalation
  → Writes final response and clicks Solve Ticket

On Solve:
  → Full conversation sent to LLM with the scenario rubric
  → Score (0–100) + written feedback returned in ~3 seconds
  → Grade note posted on the ticket

Trainer debriefs with the trainee using the grade note.
```

The AI customer simulation is **tightly constrained by the scenario YAML** — what
the customer knows, what they don't know, and how they behave are all defined by
the scenario author. The LLM cannot invent facts that aren't in the scenario.

---

## Repository Structure

```
litmus-lab/
│
├── scenarios/                          ← Training scenario definitions (YAML)
│   ├── dh-s01-opcua-bad-disconnected.yaml   ← DeviceHub: OPC UA Bad:Disconnected
│   ├── dh-s02-modbus-false-disconnect.yaml  ← DeviceHub: Modbus false Disconnected
│   └── screenshots/                    ← Pre-captured screenshots per scenario
│       └── README.md
│
├── app/
│   ├── main.py                         ← FastAPI routes
│   ├── chat.py                         ← AI customer simulation
│   ├── grader.py                       ← AI grading logic
│   ├── database.py                     ← SQLite schema + CRUD helpers
│   └── templates/
│       ├── base.html                   ← Shared layout (sepia theme)
│       ├── queue.html                  ← Ticket list
│       ├── new_ticket.html             ← Create ticket form
│       └── ticket.html                 ← Ticket conversation view
│
├── Dockerfile                          ← Production container build
├── docker-compose.yml                  ← App + nginx orchestration
├── nginx.conf                          ← Reverse proxy config (CF header passthrough)
│
├── scripts/
│   └── list_scenarios.py               ← CLI — list scenarios with metadata
│
├── _legacy/                            ← Archived earlier phases (see _legacy/README.md)
│
├── .env.example                        ← Environment variable template
├── requirements.txt                    ← Python dependencies
└── README.md                           ← This file
```

---

## Prerequisites

- **Python 3.12+** (for local dev)
- **Docker + Docker Compose** (for production deployment)
- **An OpenAI-compatible API endpoint** — the company's internal AI API, OpenAI
  direct, Azure OpenAI, or a local server like LM Studio
- **Screenshots** for each scenario — see `scenarios/screenshots/README.md`

---

## Local Setup (Dev)

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```bash
LITMUS_API_BASE=https://ai.internal.yourcompany.com/v1
LITMUS_API_KEY=your-key-here

# Optional — defaults to gpt-4o-mini
LITMUS_CHAT_MODEL=gpt-4o-mini
LITMUS_GRADE_MODEL=gpt-4o-mini
```

The app uses the same endpoint for both AI customer simulation and grading.
Any OpenAI-compatible API works: company internal, OpenAI direct, Azure OpenAI,
or a local server like LM Studio (`LITMUS_API_BASE=http://localhost:1234/v1`).

SSL certificate verification is disabled by default — required for internal
company endpoints that use self-signed or private CA certificates.

### 3. Start the server

```bash
uvicorn app.main:app --reload
```

Open `http://localhost:8000`.

> **No API key?** The app still works — customer replies will be generic
> fallbacks, and grading will fail with an informative error note on the ticket
> instead of crashing.

### 4. (Optional) Add screenshots

Follow `scenarios/screenshots/README.md`. Tickets work without screenshots but
the diagnostic experience is richer with them.

---

## Production Deployment (Docker)

The app ships as a Docker container fronted by nginx. Designed for deployment on
a VM behind Cloudflare WARP/Access.

### 1. Build and start

```bash
cp .env.example .env
# Fill in LITMUS_API_BASE and LITMUS_API_KEY in .env

docker compose up -d --build
```

The app is now reachable at `http://your-server` (port 80).

### 2. Persistent data

The SQLite database is stored in a named Docker volume (`litmus_data`) mounted
at `/data` inside the container. It survives container restarts and rebuilds.

```bash
# Back up the database
docker run --rm -v litmus_data:/data -v $(pwd):/backup alpine \
  cp /data/litmus_lab.db /backup/litmus_lab.db
```

### 3. Updating

```bash
git pull
docker compose up -d --build
```

The volume is preserved; no data is lost on update.

---

## Cloudflare Access Integration

When deployed behind **Cloudflare Access**, the authenticated user's email is
automatically injected as the `Cf-Access-Authenticated-User-Email` header. The
app reads this header to pre-populate the trainee name field on the "New Ticket"
form — so trainees don't need to type their name.

The nginx config forwards this header to the app:

```nginx
proxy_set_header Cf-Access-Authenticated-User-Email
                 $http_cf_access_authenticated_user_email;
```

To test locally:

```bash
curl -H "Cf-Access-Authenticated-User-Email: jane.doe@company.com" \
  http://localhost:8000/new
```

The trainee field will be pre-filled with `jane.doe@company.com`.

---

## Running a Training Session

### Step 1 — Create the ticket (Trainer)

Open `http://your-server/new`, select a scenario, and enter the trainee's name.
Click **Create Ticket**. Share the ticket URL or sit with the trainee.

### Step 2 — Trainee works the ticket

The trainee reads the customer's opening message and any attached screenshots,
then asks the customer clarifying questions using the reply box.

**The AI customer replies immediately**, staying strictly in character based on
the scenario definition. The customer only knows what the scenario says they
know — they cannot accidentally reveal the root cause.

Example conversation (le-s01):

> **Trainee:** Can you open DeviceHub and check what status PLC-Line3 shows?
>
> **Carlos Mendes:** I just opened DeviceHub and found PLC-Line3. It shows a
> red icon and says "Stopped". I assumed it was a display glitch since the
> hardware is definitely online. Is that the problem?
>
> **Trainee:** Yes — that's the issue. The device is in a Stopped state in
> Litmus Edge, which means it has stopped polling the PLC and publishing data.
> To fix it: go to DeviceHub, find PLC-Line3, and click the ▶ Start button.
> Once it shows as Running, check that data is flowing again in the tag list.

### Step 3 — Solve the ticket

- **Resolve scenarios (le-s01 to le-s04):** Write a clear solution guide, leave
  Escalation unchecked, click **Solve Ticket**.
- **Escalation scenarios (le-s05, le-s06):** Check **Mark as Escalation**, write
  an escalation note with all diagnostic context, click **Solve Ticket**.

Grading runs immediately. The grade note appears on the ticket within ~3 seconds.

### Step 4 — Debrief

```
LITMUS LAB — TRAINING GRADE
──────────────────────────────────────────────────
Trainee:         Jane Doe
Scenario:        le-s01 — Device stopped publishing data to MQTT
Expected action: RESOLVE
Model:           gpt-4o-mini

Score:           85/100  ✅ PASSED
Correct action:  ✅ Yes

KEY OBSERVATIONS:
  • Correctly identified the stopped device state from the screenshot
  • Provided accurate DeviceHub → Start instructions
  • Did not ask the customer to confirm data resumed — minor gap

TRAINER FEEDBACK:
  [2–3 paragraphs of specific written feedback addressed to the trainee]
──────────────────────────────────────────────────
```

---

## Scenario Reference

### DeviceHub Scenarios

| ID | Title | Action | Difficulty |
|----|-------|--------|-----------|
| `dh-s01` | OPC UA tags stuck at Bad:Disconnected despite device showing Connected | Resolve | Intermediate |
| `dh-s02` | Modbus device shows Disconnected but tag data is still flowing | Resolve | Beginner |

**Suggested training order:** dh-s02 → dh-s01

Start with dh-s02 (beginner) so trainees learn to distinguish UI status from actual data
flow before tackling the more diagnostic dh-s01 (OPC UA subscription errors).

---

## How Grading Works

When a ticket is solved, the app:

1. Collects the full public comment thread (customer + trainee messages)
2. Loads the scenario's `grading_rubric` and `root_cause` fields
3. Detects whether the Escalation checkbox was checked
4. Sends everything to the configured LLM with a structured grading prompt
5. Parses the JSON response into a score + feedback
6. Stores the score on the ticket (visible in the queue list)
7. Posts the formatted grade note on the ticket as an internal note

**Score breakdown (typical resolve scenario):**
- 50 pts — Correct root cause identified
- 25 pts — Accurate resolution/escalation steps
- 15 pts — Professional, clear communication
- 10 pts — Asked customer to verify the fix

**Passing threshold:** 70/100

**Critical penalties:**
- Escalating when the issue is L0-fixable: −40 pts
- NOT escalating when escalation is required: −50 pts (automatic ≤50 score cap)

Grading is non-deterministic. Treat scores as guidance, not objective
measurements. The written feedback paragraph is more valuable than the number.

---

## Adding New Scenarios

Create a YAML file in `scenarios/` using this schema:

```yaml
id: le-s07                          # unique ID, used in the UI and DB
title: Short descriptive title
difficulty: beginner | intermediate | advanced
expected_action: resolve | escalate

customer:
  name: Customer Name
  company: Company Name
  le_version: "4.0.6"

ticket:
  subject: "Subject line for the ticket"
  initial_message: |
    The customer's opening message. Written in first person.
    Include symptoms, what they've already checked, and urgency level.

  attachments:                      # optional; paths relative to scenarios/screenshots/
    - le-s07/screenshot1.png

diagnostic_checklist:               # shown in the sidebar to guide the trainee
  - "Question 1 to prompt structured thinking"
  - "Question 2"
  - "Question 3"

root_cause: |
  Internal explanation of what's actually wrong.
  Not shown to the trainee — used by the grader only.

correct_response_summary: |         # for resolve scenarios
  1. Step one the trainee should take
  2. Step two
  3. Step three

escalation_reason: |                # for escalate scenarios (replaces correct_response_summary)
  Why this cannot be fixed at L0 and what engineering needs to do.

grading_rubric: |
  Point-by-point grading instructions for the LLM.
  Use named sections with point values (e.g. "CRITICAL (50 pts): ...").
  Score range: 0–100. Passing threshold: 70.

# ── AI customer simulation context ───────────────────────────────────────────
customer_ai_context:
  knows: |
    - Bullet list of facts the customer knows and can report
    - Include specific values, status indicators, and things they observed
    - Be specific — "the device shows red icon and status Stopped" not "device has an issue"
  does_not_know: |
    - Things the customer cannot reveal (root cause, technical internals)
    - Things they genuinely don't know
  behavior: |
    - How the customer communicates (technical? non-technical? urgent? confused?)
    - What they do when asked to check something in the UI
    - Any specific pushback or constraints (e.g., "can't roll back", "appliance is locked")
```

Then add screenshots to `scenarios/screenshots/le-s07/` and restart the server.
Run `python scripts/list_scenarios.py --verbose` to verify the YAML is valid.

### Tips for good `customer_ai_context`

- **`knows`** — be as specific as the scripted replies used to be. Include exact
  status text, exact error messages, exact values. The AI uses this to answer
  questions accurately.
- **`does_not_know`** — list the root cause and any technical details that would
  make the scenario too easy to solve without investigation.
- **`behavior`** — define the customer's persona and response patterns. A
  non-technical operations manager behaves very differently from an automation
  engineer. Mention urgency level and any notable constraints.

---

## Escalation vs. Resolution

Teaching trainees *when* to escalate is as important as teaching them *how* to
resolve. The escalation scenarios (le-s05, le-s06) are designed to penalise
incorrect resolution attempts heavily.

**L0 analysts should escalate when:**
- The issue is a confirmed platform bug requiring a software patch or firmware upgrade
- The fix requires appliance-level access beyond what the Litmus Edge UI provides
- The issue involves data corruption or production data integrity risk
- No configuration change in the Litmus Edge UI can resolve the problem

**L0 analysts should NOT escalate when:**
- The root cause is a configuration gap (missing tags, wrong group assignment)
- The fix is a UI action (start a stopped device, start a stopped service)
- The customer can follow step-by-step instructions to resolve it themselves

---

## Architecture

```
[Employee browser]
        │  (Cloudflare WARP VPN)
[Cloudflare Access]  ← SSO authentication, injects user email header
        │
[nginx :80]          ← reverse proxy, forwards CF-Access header
        │
[FastAPI app :8000]  ← reads CF header, serves UI, calls AI API
        │
    ┌───┴────────────────────────────┐
    │                                │
[SQLite DB]               [Company AI API]
(tickets + comments,      (OpenAI-compatible endpoint)
 WAL mode for concurrent     ├─ LITMUS_CHAT_MODEL → customer simulation
 multi-user access)          └─ LITMUS_GRADE_MODEL → ticket grading
```

**Key design decisions:**
- **Single AI endpoint** — `LITMUS_API_BASE` routes both chat and grading through
  the company's internal API. No external dependencies.
- **Scenario-constrained AI** — the `customer_ai_context` YAML block becomes the
  AI's system prompt. The AI cannot invent facts outside this context.
- **WAL mode SQLite** — supports multiple simultaneous trainee sessions without
  write contention.
- **Stateless app layer** — the full conversation history is loaded from the DB
  on every request; no in-memory session state.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LITMUS_API_BASE` | Yes | — | Base URL of the OpenAI-compatible API |
| `LITMUS_API_KEY` | Yes | — | API key for the endpoint |
| `LITMUS_CHAT_MODEL` | No | `gpt-4o-mini` | Model for customer simulation |
| `LITMUS_GRADE_MODEL` | No | `gpt-4o-mini` | Model for grading |
| `LITMUS_DATA_DIR` | No | `.` (project root) | Directory for the SQLite DB file |

---

## Legacy Code

The `_legacy/` directory contains retired code from earlier phases:

- **Phase 1/2** — FastAPI app with live Litmus Edge SDK integration
- **Phase 3** — Zendesk-integrated approach with real tickets and a polling grader

See [`_legacy/README.md`](_legacy/README.md) for full details.
