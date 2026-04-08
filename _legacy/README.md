# Legacy Code — Litmus Lab Phases 1, 2 & 3 (Retired Approaches)

This directory contains retired Litmus Lab application code from three earlier phases.

**Do not delete this directory until the current system is fully validated in production.**

---

## What was here

### Phase 1 — FastAPI web app with live Litmus Edge integration

A self-contained web application (FastAPI + Jinja2) that connected to a live
Litmus Edge 4.x instance via the official SDK and created intentionally broken
states for learners to diagnose and fix.

**Architecture:**
- `app/main.py` — FastAPI routes and app lifecycle
- `app/engine.py` — Scenario lifecycle manager (setup / validate / teardown)
- `app/litmus_utils.py` — Helper functions wrapping the Litmus SDK
- `app/scenarios/base.py` — Abstract base class for all scenarios
- `app/scenarios/plc_01_debug_flood.py` — Phase 2 active scenario
- `app/scenarios/archive/` — Phase 1 scenarios (DH-01 through SYS-02)
- `app/templates/` — Jinja2 HTML templates (dark-themed ticket queue UI)
- `Dockerfile` — Docker build for the web app
- `test_tags.py` — Ad-hoc SDK testing script

### Why it was retired

The live-LE approach had fundamental constraints that made it unsuitable for
scalable L0 support training:

1. **One active scenario at a time** — the app held a single global scenario
   slot. Multiple concurrent trainees was not possible without a major rewrite.

2. **Trainee had direct LE access** — but L0 support analysts in the real job
   do NOT have direct access to customer LE instances. Training them to click
   inside LE was training the wrong skill.

3. **Infrastructure complexity** — Docker container, SDK dependency, shared LE
   instance, broken-state lifecycle management, and Zendesk webhook inbound
   connectivity all compounded into a fragile system.

4. **Wrong training goal** — real L0 work is: read customer symptoms, diagnose
   from screenshots, write clear remediation steps, and know when to escalate.
   None of that requires touching LE directly.

### What replaced it (Phase 3 — Zendesk-based)

See `_legacy/zendesk-phase/` for what came next: a Zendesk-integrated system
that created real Zendesk tickets and polled for solved ones to grade them.
That approach was also retired — see below.

---

## Phase 3 — Zendesk Integration (also retired)

### What was here

`_legacy/zendesk-phase/` contains the Zendesk-based training system:

- `zendesk_client.py` — Zendesk REST API wrapper (ticket creation, comments, search)
- `reply_watcher.py` — Polls for active tickets and posts scripted customer replies
- `create_ticket.py` — CLI: `python scripts/create_ticket.py le-s01 trainee@company.com`
- `grade_tickets.py` — Background poller: grades solved tickets via Claude, posts internal notes

**Architecture:**
- No web server — just Python scripts and a Zendesk account
- Trainees worked entirely within real Zendesk
- Scripted customer replies triggered by keyword matching in trainee comments
- Claude graded responses when trainee marked ticket Solved

**Why it was retired:**

The Zendesk API integration worked well, but it was determined that the training
goal is **diagnostic and escalation skills**, not Zendesk familiarity (trainees
have separate Zendesk onboarding). Requiring a real Zendesk account, API tokens,
and a service account added unnecessary friction for running a training session.
A self-contained simulation achieves the same educational outcome without
any external account dependencies.

### What replaced it (Phase 4 — current)

See the project root for the self-contained FastAPI simulation:
- `app/main.py` — FastAPI web app (ticket queue, conversation view, grading)
- `app/database.py` — SQLite persistence (tickets + comments)
- `app/templates/` — Jinja2 ticket UI (dark-themed, Zendesk-like)
- `app/grader.py` — Claude API grading (unchanged from Phase 3)
- `scenarios/` — YAML scenario files (unchanged)

Start with: `uvicorn app.main:app --reload`

### Scenario knowledge preserved

The technical knowledge in the archived scenarios translated directly into the
YAML scenario content:

| Legacy scenario | New YAML scenario | Type |
|----------------|-------------------|------|
| `dh_01_stopped_device.py` | `le-s01-stopped-device.yaml` | Resolve |
| `dh_02_no_tags.py` | `le-s02-tagless-device.yaml` | Resolve |
| `sys_02_service_stopped.py` | `le-s03-ssh-stopped.yaml` | Resolve |
| `sys_01_permissions.py` | `le-s04-viewer-permissions.yaml` | Resolve |
| `dh_03_alias_topics.py` | *(no direct equivalent — deeper than L0)* | — |
| `plc_01_debug_flood.py` | *(no direct equivalent — trainee had direct LE access)* | — |
