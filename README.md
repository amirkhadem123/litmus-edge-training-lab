# Litmus Lab — Litmus Support Practice Certificate

A self-contained web application for training Litmus Edge Customer Support Analysts.
Trainees work through realistic simulated support tickets, chat with a scripted AI
customer, diagnose the root cause, and receive instant multi-dimensional AI-graded
feedback. No trainer required. No live Litmus Edge instance needed.

> **v2 (this branch)** replaces the trainer-led ticket workflow with a fully
> autonomous, self-paced certificate program structured around three graded
> checkpoints.

---

## Table of Contents

1. [How It Works](#how-it-works)
2. [Certificate Program Structure](#certificate-program-structure)
3. [Repository Structure](#repository-structure)
4. [Prerequisites](#prerequisites)
5. [Local Setup (Dev)](#local-setup-dev)
6. [Production Deployment (Docker)](#production-deployment-docker)
7. [Scenario Reference](#scenario-reference)
8. [How Grading Works](#how-grading-works)
9. [Adding New Scenarios](#adding-new-scenarios)
10. [AI Provider Configuration](#ai-provider-configuration)
11. [Admin View](#admin-view)
12. [Architecture](#architecture)
13. [Environment Variables](#environment-variables)

---

## How It Works

```
Trainee visits the app
  → Enters their name → dashboard shown
  → Certificate checkpoints (CP1 → CP2 → CP3) unlock sequentially on pass
  → Practice scenarios always available

Trainee begins a checkpoint or practice attempt
  → Customer's opening support ticket displayed
  → Trainee types replies to gather diagnostic information
      (scripted keyword-matching replies — no generative AI, fully deterministic)
  → Trainee clicks Resolve or Escalate, writes a final note
  → Grading runs in background (~5–10 seconds)
  → Multi-dimensional score + per-dimension feedback shown

Repeat until all three checkpoints are passed → certificate complete
```

**Customer simulation is scripted**, not generative. Each scenario defines a list
of keyword triggers and pre-written replies. This ensures every trainee who asks
the right diagnostic question gets the right information — regardless of phrasing —
making grading fair and reproducible.

**Grading is AI-powered** (OpenAI-compatible endpoint). The LLM evaluates each
rubric dimension independently. Critical score caps (e.g. wrong resolve/escalate
decision) are enforced in Python after the JSON is parsed — the LLM cannot
soften or override them.

---

## Certificate Program Structure

### Checkpoints

| # | ID | Title | Difficulty | Expected Action |
|---|-----|-------|-----------|----------------|
| 1 | `cp-01` | Dashboard data stopped updating — plant floor sensor | Beginner | Resolve |
| 2 | `cp-02` | OPC UA tags show Good quality but values appear frozen | Intermediate | Resolve |
| 3 | `cp-03` | DeviceHub restarts every few hours, disconnecting all devices | Advanced | Escalate |

**Unlock rules:**
- CP1 is available immediately
- CP2 unlocks when CP1 is passed (≥ 70/100)
- CP3 unlocks when CP2 is passed
- Each checkpoint allows a maximum of 2 attempts
- After 2 failed attempts, the checkpoint is locked (no further re-attempts)

**Pass threshold:** 70/100 for all checkpoints.

**Critical penalty:** Choosing the wrong action (e.g. escalating a resolvable issue,
or resolving when escalation is required) caps the score at ≤ 50 for CP3.

### Practice Mode

Practice scenarios are always available with no unlock requirement and do not
count toward the certificate. Useful for warming up before checkpoints.

| ID | Title | Difficulty | Expected Action |
|----|-------|-----------|----------------|
| `dh-s01` | OPC UA tags stuck at Bad:Disconnected despite device showing Connected | Intermediate | Resolve |
| `dh-s02` | Modbus device shows Disconnected but tag data is still flowing | Beginner | Resolve |

---

## Repository Structure

```
litmus-lab/
│
├── scenarios/                              ← Training scenario definitions (YAML)
│   ├── cp-01-define-the-problem.yaml       ← Checkpoint 1: stopped device
│   ├── cp-02-investigate.yaml              ← Checkpoint 2: frozen OPC UA tags
│   ├── cp-03-capstone.yaml                 ← Checkpoint 3: DeviceHub OOM restarts
│   ├── dh-s01-opcua-bad-disconnected.yaml  ← Practice: OPC UA Bad:Disconnected
│   └── dh-s02-modbus-false-disconnect.yaml ← Practice: Modbus false disconnect
│
├── app/
│   ├── main.py          ← FastAPI routes (all application logic)
│   ├── database.py      ← SQLite schema + CRUD helpers
│   ├── scenarios.py     ← YAML loader, keyword matcher, urgency injection
│   ├── grader.py        ← Dimensional grading, penalty enforcement
│   └── templates/
│       ├── base.html           ← Shared layout (sepia theme)
│       ├── start.html          ← Trainee name entry page
│       ├── dashboard.html      ← Checkpoint cards + practice table
│       ├── attempt.html        ← Live ticket conversation view
│       ├── results.html        ← Grade breakdown page
│       ├── settings.html       ← AI provider configuration
│       ├── admin.html          ← Admin: all trainees + progress (password-protected)
│       └── admin_attempt.html  ← Admin: individual attempt detail
│
├── Dockerfile           ← Production container build
├── docker-compose.yml   ← App + nginx orchestration
├── nginx.conf           ← Reverse proxy config
├── .env.example         ← Environment variable template
├── requirements.txt     ← Python dependencies
└── README.md            ← This file
```

---

## Prerequisites

- **Python 3.12+** (for local dev)
- **Docker + Docker Compose** (for production deployment)
- **An OpenAI-compatible API endpoint** — Anthropic Claude, Google Gemini, or any
  OpenAI-compatible server (Open WebUI, LM Studio, Azure OpenAI, etc.)

---

## Local Setup (Dev)

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Start the server

```bash
uvicorn app.main:app --reload
```

Open `http://localhost:8000` and go to `/settings` to configure your AI provider.

The app starts without any `.env` file. AI settings are configured through the
web UI at `/settings` and stored in the SQLite database.

### 3. (Optional) Seed environment variables

If you prefer environment variables over the UI, copy `.env.example`:

```bash
cp .env.example .env
```

Edit `.env`:

```bash
LITMUS_API_BASE=https://api.anthropic.com/v1
LITMUS_API_KEY=sk-ant-...
LITMUS_GRADE_MODEL=claude-haiku-4-5-20251001
```

Environment variables serve as defaults; settings saved through the UI take
precedence.

### 4. Fresh start

To reset all trainee progress, delete the database file:

```bash
rm litmus_lab.db
```

The app recreates the schema automatically on next startup.

---

## Production Deployment (Docker)

### 1. Build and start

```bash
cp .env.example .env
# Fill in LITMUS_API_BASE and LITMUS_API_KEY in .env

docker compose up -d --build
```

The app is reachable at `http://your-server` (port 80, fronted by nginx).

### 2. Persistent data

The SQLite database is stored in a Docker volume (`litmus_data`) at `/data`
inside the container. It survives restarts and rebuilds.

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

Data is preserved. No migration needed — the schema is recreated from scratch
only if the database file doesn't exist.

### 4. Admin access

Visit `http://your-server/admin?pw=YOUR_ADMIN_PASSWORD`.

Set the password via the `LITMUS_ADMIN_PASSWORD` environment variable. If the
variable is not set, the admin page is inaccessible.

---

## Scenario Reference

### Scenario YAML structure

Every scenario defines:

```yaml
id: cp-01                            # unique identifier
title: "Short descriptive title"
mode: certificate | practice         # certificate → checkpoint; practice → always available
checkpoint: 1                        # 1, 2, or 3 (certificate only)
difficulty: beginner | intermediate | advanced
expected_action: resolve | escalate

customer:
  name: Customer Name
  company: Company Name
  le_version: "4.0.6"

ticket:
  subject: "Subject line"
  initial_message: |
    Customer's opening email. Written in first person.

diagnostic_checklist:
  - "Checklist item shown in the sidebar to guide the trainee"

root_cause: |
  Internal explanation. NOT shown to the trainee — used by the grader only.

correct_response_summary: |          # for resolve scenarios
  1. Step one
  2. Step two

# Scripted keyword-triggered customer replies
scripted_replies:
  - triggers:
      - "log"
      - "device log"
      - "check the log"
    reply: |
      I've opened the device log. I see the following error repeating...

  - triggers:
      - "restart"
    reply: |
      I tried restarting but the issue came back within minutes.

fallback_reply: |
  I'm not sure what you mean. Could you be more specific?

# Urgency injection (optional — CP3 only)
urgency_injection:
  enabled: true
  trigger_after_customer_message: 3  # fires on the 3rd customer reply
  text: |
    I should also mention — we have a compliance audit in 48 hours...

# Dimensional grading rubric
grading_rubric:
  pass_threshold: 70
  dimensions:
    - name: Proactive first response
      max_points: 40
      description: |
        Award full points if the trainee immediately directed the customer to
        DeviceHub to check device status...

    - name: Symptom extraction
      max_points: 35
      description: |
        Award full points if the trainee gathered: device status, timing,
        and recent changes...

  critical_penalties:
    - condition: wrong_direction
      cap: cap_at_50
      applies_to_checkpoints: [3]    # empty list [] = never applies

    - condition: sequence_skipped
      cap: cap_at_40
      applies_to_checkpoints: [2]
```

### Keyword matching

The customer reply engine uses case-insensitive partial matching. The first
matching trigger in the `scripted_replies` list wins, so order from
most-specific to least-specific.

A trigger of `"log"` matches any trainee message containing the word "log"
(e.g. "please check the device log", "can you open the log file?").

---

## How Grading Works

When a trainee submits their final note, grading runs in the background:

1. Full conversation transcript sent to the configured LLM with:
   - Scenario root cause and correct response summary
   - Dimensional rubric (one dimension at a time)
   - Instructions to return structured JSON

2. LLM returns per-dimension scores and feedback paragraphs

3. Python recomputes `total_score = sum(dimension scores)` — the LLM's self-reported
   total is discarded to prevent score softening

4. Critical penalties applied in Python:
   - `wrong_direction`: trainee chose Resolve when expected Escalate (or vice versa)
   - `sequence_skipped`: trainee jumped to the answer without diagnostic steps (CP2)

5. `passed = total_score >= pass_threshold` (70)

6. Grade stored in DB; checkpoint progress updated; next checkpoint unlocked if passed

**Score example (CP1 — 3 dimensions):**

| Dimension | Max | Example Score |
|-----------|-----|--------------|
| Proactive first response | 40 | 36 |
| Symptom extraction | 35 | 28 |
| Resolution accuracy | 25 | 20 |
| **Total** | **100** | **84 — ✅ Passed** |

Grading is non-deterministic. The written per-dimension feedback is more
actionable than the numeric score. Treat scores as directional guidance.

---

## Adding New Scenarios

### Certificate scenarios

Create a file `scenarios/cp-04-yourtitle.yaml` following the schema above.
Set `mode: certificate` and `checkpoint: 4`. Update checkpoint unlock logic in
`app/database.py` if adding beyond CP3 (currently hardcoded for 1–3).

### Practice scenarios

Create `scenarios/dh-s03-yourtitle.yaml` (or `int-s01-`, `sys-s01-`, etc.)
with `mode: practice`. No other changes needed — the dashboard picks up all
`mode: practice` scenarios automatically.

### Authoring scripted replies

Good scripted replies follow these principles:

- **Be specific in `knows`** — include exact status text, exact error messages,
  exact field values. Vagueness forces trainees to guess instead of diagnose.
- **Order triggers from specific to general** — "device log" before "log" if
  both are defined, so the more specific trigger wins.
- **Cover all diagnostic paths** — every question a well-trained analyst would
  ask should have a matching scripted reply. Use the `fallback_reply` to catch
  unexpected questions, not as a substitute for coverage.
- **Match the customer's technical level** — non-technical customers should use
  plain language; controls engineers can use Modbus/OPC UA terminology.

---

## AI Provider Configuration

Visit `/settings` in the app to configure the AI provider. Settings are stored
in the database and override environment variables.

### Supported providers

| Provider | Base URL | Notes |
|----------|----------|-------|
| Open WebUI | Your internal URL | SSL verification disabled (self-signed certs) |
| Anthropic Claude | `https://api.anthropic.com/v1` | Default grade model: `claude-haiku-4-5-20251001` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | Default: `gemini-2.0-flash` |

All providers use the OpenAI-compatible SDK. No Anthropic or Google SDK required.

### Recommended model

`claude-haiku-4-5-20251001` — fast, accurate at structured JSON output, cost-effective
for grading. Set as the default for all providers in the UI presets.

### Testing

Use the **Test Connection** button in `/settings` to verify the endpoint and key
are working before running a graded attempt.

---

## Admin View

`GET /admin?pw=YOUR_ADMIN_PASSWORD`

Shows:
- All registered trainees with registration date
- Checkpoint progress (CP1/CP2/CP3 status + best scores)
- Last 5 attempts per trainee with links to full conversation + grade breakdown

The admin password is set via the `LITMUS_ADMIN_PASSWORD` environment variable.
If unset, the admin page returns 403 for all requests.

---

## Architecture

```
[Browser]
   │
[nginx :80]          ← reverse proxy
   │
[FastAPI app :8000]  ← cookie session (trainee_id), background grading tasks
   │
 ┌─┴─────────────────────────────┐
 │                               │
[SQLite DB (WAL mode)]   [AI Grading API]
  ├─ trainees                (OpenAI-compatible)
  ├─ attempts
  ├─ messages
  ├─ grades
  ├─ checkpoint_progress
  └─ settings
```

**Key design decisions:**

- **Scripted customer simulation** — deterministic keyword matching instead of
  generative AI. Every trainee who asks the right question gets the right answer.
  This is mandatory for fair grading.

- **Penalties enforced in Python** — score caps for wrong direction and skipped
  diagnostic sequences are applied after the LLM response is parsed. The LLM
  cannot soften them.

- **Background grading** — FastAPI `BackgroundTasks` runs grading after the HTTP
  response is returned. The results page polls every 3 seconds until grading
  completes.

- **Cookie session** — trainee identity stored as a plain integer `trainee_id`
  cookie (HttpOnly). No encryption needed — IDs are not security-sensitive.

- **Single API endpoint for all providers** — OpenAI SDK with configurable
  `base_url`. Works for Claude via Anthropic's OpenAI-compatible endpoint,
  Gemini via Google's compatibility layer, and any self-hosted server.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LITMUS_API_BASE` | No | — | Base URL of the AI API (overridden by UI setting) |
| `LITMUS_API_KEY` | No | — | API key (overridden by UI setting) |
| `LITMUS_GRADE_MODEL` | No | `claude-haiku-4-5-20251001` | Grading model (overridden by UI) |
| `LITMUS_PROVIDER` | No | `claude` | Provider name (`openwebui`, `claude`, `gemini`) |
| `LITMUS_DATA_DIR` | No | `.` (project root) | Directory for the SQLite DB file |
| `LITMUS_ADMIN_PASSWORD` | No | — | Password for `/admin` (no admin access if unset) |
