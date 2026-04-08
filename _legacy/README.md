# Legacy Code — Litmus Lab Phase 1 & Phase 2 (Live LE Approach)

This directory contains the original Litmus Lab application, which was retired
in favour of the Zendesk-based L0 training approach on the `feature/zendesk-l0-training`
branch.

**Do not delete this directory until the new system is fully validated in production.**

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

### What replaced it

See the project root for the Zendesk-based approach:
- `scenarios/` — YAML scenario files (content-based, no SDK needed)
- `scripts/` — Trainer CLI tools
- `app/zendesk_client.py` — Zendesk REST API wrapper
- `app/grader.py` — Claude API grading

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
