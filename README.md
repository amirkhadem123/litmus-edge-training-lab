# Litmus Lab

A hands-on troubleshooting trainer for **Litmus Edge 4.x**.

Litmus Lab is a Python web application that runs as a Docker container **inside** a Litmus Edge instance. It uses the official Litmus SDK to inject controlled, realistic problems into the live platform, then challenges learners to find and fix them using the real Litmus Edge UI.

---

## Branches

| Branch | Description |
|--------|-------------|
| `main` | Phase 1 — five proof-of-concept scenarios, simple scenario-card UI |
| `stage/v2-ticket-ux` | Phase 2 — ticket-based UX, retired Phase 1 scenarios, new realistic scenario |

Phase 2 is currently in review. The plan is to merge to `main` once validated on a live Litmus Edge 4.0.x instance.

---

## How It Works

| Step | Who does it | What happens |
|------|-------------|--------------|
| 1 | Learner | Picks a ticket from the support queue |
| 2 | **Litmus Lab** | Calls the Litmus Edge API to inject a broken state (misconfigured device, wrong settings, etc.) |
| 3 | Learner | Switches to the Litmus Edge UI and investigates — no hints about what's wrong |
| 4 | Learner | Clicks **Mark Resolved** when they believe the issue is fixed |
| 5 | **Litmus Lab** | Queries the API to verify the fix, reports pass or fail |
| 6 | **Litmus Lab** | Cleans up all resources it created on reset or timeout |

---

## Scenarios

### Phase 2 — Active (branch: `stage/v2-ticket-ux`)

| Ticket | Title | Priority | What's injected |
|--------|-------|----------|-----------------|
| `TKT-0042` | DeviceHub flooding log storage — suspected misconfiguration on PLC controller | HIGH | A device (`lab-plc-controller`) is created with `debug=True`. Data flows normally — the only symptom is log flooding, which the learner must trace back to the device's debug setting. |

**Resolution path:** DeviceHub → find `lab-plc-controller` → Edit → disable Debug mode → save.

**Validation:** The app re-reads the device's `debug` attribute from the Litmus Edge API. Success when `debug == False`.

---

### Phase 1 — Archived (branch: `main`, files in `app/scenarios/archive/`)

These five scenarios remain in the codebase as reference implementations. They are not loaded by the app (the auto-discovery does not scan subdirectories). They demonstrate every supported SDK pattern and are the best starting point for writing new scenarios.

| ID | Title | Category | Difficulty | What breaks |
|----|-------|----------|------------|-------------|
| `dh-01` | The Stopped Device | DeviceHub | Beginner | A device is stopped — appears in DeviceHub but publishes 0 messages |
| `dh-02` | The Tagless Device | DeviceHub | Beginner | A device is running but has zero tags configured |
| `dh-03` | The Silent Alias | DeviceHub | Intermediate | `alias_topics=False` on a running device — MQTT flow subscriptions by name receive nothing |
| `sys-01` | The Locked-Out Engineer | System | Beginner | A user account has Viewer-only permissions and cannot modify DeviceHub |
| `sys-02` | The Dead Service | System | Intermediate | The SSH service is stopped — engineers can no longer connect to the device |

---

## UX Design Philosophy (Phase 2)

Phase 1 presented each scenario as an educational exercise — the UI showed a scenario title, difficulty badge, learning objective, and a labelled "What you observe" box. This made it obvious what category of problem the learner was about to face.

Phase 2 replaces this with a **support ticket queue**. The learner sees only:

- A ticket number and priority badge
- A subject line written as a customer complaint
- A description written in the first person by a fictional customer

There is no difficulty indicator, no category, and no learning objective in the UI. The learner must treat it as a real ticket: open Litmus Edge, investigate, and resolve it on their own. Hints are available on request but are intentionally vague at first.

This design better reflects how engineers encounter real problems on customer sites.

---

## Requirements

- **Litmus Edge 4.x** running on a VM or ISO install (not a Docker deployment — the Marketplace requires VM/ISO)
- **Docker** available on the machine where you will build and run this app
- A Litmus Edge **OAuth2 API token** with administrator-level permissions
- The **litmussdk wheel file** (`litmussdk-2.0.1-py3-none-any.whl`) placed in the `resources/` folder

---

## Setup

### 1. Get the Litmus SDK wheel

Obtain `litmussdk-2.0.1-py3-none-any.whl` from your Litmus contact and place it at:

```
resources/litmussdk-2.0.1-py3-none-any.whl
```

> The `resources/` folder is listed in `.gitignore` and is never committed to git.

### 2. Create an OAuth2 API token in Litmus Edge

1. Log into Litmus Edge as an administrator.
2. Go to **System → Access Control → Tokens**.
3. Click **Add Token** and select **OAuth2 Client**.
4. Give it a name (e.g. `litmus-lab`), set an appropriate expiry, and assign it to a group with full administrator permissions.
5. Copy the **Client ID** and **Client Secret** — you will need these in the next step.

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in:

```env
EDGE_URL=https://192.168.1.50        # Your Litmus Edge IP
EDGE_API_CLIENT_ID=your-client-id
EDGE_API_CLIENT_SECRET=your-secret
VALIDATE_CERTIFICATE=false           # Leave false for self-signed certs
```

### 4. Build and run

```bash
docker build -t litmus-lab . && docker run --rm -p 8000:8000 --env-file .env litmus-lab
```

Open [http://localhost:8000](http://localhost:8000).

**To run inside Litmus Edge via the Marketplace:**

1. Push the image to a container registry accessible from your Litmus Edge device.
2. In the Litmus Edge UI, go to **Applications → Marketplace → Private Registry**.
3. Add the registry and deploy the `litmus-lab` image.
4. Set the port mapping to `8000:8000` and pass the environment variables above.
5. Access the app at `http://<litmus-edge-ip>:8000`.

---

## Project Structure

```
litmus-lab/
├── app/
│   ├── main.py                     # FastAPI routes and app entry point
│   ├── engine.py                   # ScenarioEngine — manages scenario lifecycle
│   ├── litmus_utils.py             # Helper functions (Prometheus parsing, safe deletes)
│   ├── scenarios/
│   │   ├── __init__.py
│   │   ├── base.py                 # BaseScenario abstract class (read this first!)
│   │   ├── plc_01_debug_flood.py   # Active Phase 2 scenario
│   │   └── archive/                # Retired Phase 1 scenarios (reference only)
│   │       ├── dh_01_stopped_device.py
│   │       ├── dh_02_no_tags.py
│   │       ├── dh_03_alias_topics.py
│   │       ├── sys_01_permissions.py
│   │       └── sys_02_service_stopped.py
│   └── templates/
│       ├── base.html               # Shared HTML layout and global CSS
│       ├── index.html              # Ticket queue (home page)
│       └── scenario.html           # Individual ticket view
├── resources/                      # NOT committed to git (see .gitignore)
│   └── litmussdk-2.0.1-py3-none-any.whl
├── .env.example                    # Template for environment variables
├── .gitignore
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## Adding a New Scenario

1. Create a new file in `app/scenarios/`, e.g. `plc_02_my_scenario.py`.
2. Import and subclass `BaseScenario` from `scenarios.base`.
3. Set the class attributes. The required ones are `id`, `title`, `symptom`, `hints`. The ticket-specific ones are `ticket_number`, `priority`, and `customer`.
4. Implement `setup()`, `validate()`, and `teardown()`.
5. That's it — `ScenarioEngine` discovers it automatically at startup via `pkgutil.iter_modules()`.

```python
from scenarios.base import BaseScenario, ScenarioState
from litmussdk.utils.conn import LEConnection

class MyScenario(BaseScenario):
    id             = "plc-02"
    title          = "Subject line written as a customer complaint"
    ticket_number  = "TKT-0043"
    priority       = "Medium"          # "High" | "Medium" | "Low"
    customer       = "Acme Plant — Engineering Team"
    symptom        = "Full customer description of the problem..."
    hints          = [
        "Vague first hint.",
        "More specific second hint.",
        "Explicit third hint with exact steps.",
    ]

    # optional — kept in code but not shown in UI
    learning_objective = "..."
    category           = "DeviceHub"
    difficulty         = "Intermediate"

    def setup(self, conn: LEConnection, state: ScenarioState) -> None:
        # inject the broken state; append created resource IDs to state.resources
        ...

    def validate(self, conn: LEConnection, state: ScenarioState) -> tuple[bool, str]:
        # return (True, "success message") or (False, "what's still wrong")
        ...

    def teardown(self, conn: LEConnection, state: ScenarioState) -> None:
        # delete everything in state.resources
        ...
```

See `app/scenarios/archive/` for complete worked examples of every supported SDK pattern.

---

## How the Code Is Organised

### `main.py`
Defines HTTP routes and renders HTML pages. Think of it as the receptionist — it receives requests and forwards them to `ScenarioEngine`.

### `engine.py`
The brain. Manages which scenario is active, calls `setup()` / `validate()` / `teardown()`, handles the auto-timeout, and holds the Litmus API connection. One instance lives for the lifetime of the app.

### `litmus_utils.py`
Helper functions that fill gaps in the SDK. Most importantly: `get_device_running_state()`, which reads Prometheus metrics to determine whether a device is running or stopped (this information is not available via the GraphQL API).

### `scenarios/base.py`
The contract. Defines `BaseScenario` (abstract class), `ScenarioState` (dataclass), and the ticket metadata fields (`ticket_number`, `priority`, `customer`). Read this file carefully before writing a new scenario.

### `scenarios/plc_01_debug_flood.py`
The active Phase 2 scenario. Well-commented and demonstrates the device creation + property-read-back validation pattern.

### `scenarios/archive/`
The five retired Phase 1 scenarios. Not loaded by the app but preserved as reference implementations. Each file has a detailed module-level docstring explaining the scenario's mechanics.

---

## Architecture Notes

- **One scenario at a time.** Because scenarios modify live platform state, only one can be active at a time. Starting a second scenario while one is running returns an error.
- **All lab resources are prefixed `lab-`.** This makes them easy to identify in the Litmus Edge UI and ensures teardown never touches real production configuration.
- **The SDK uses GraphQL for DeviceHub, REST for everything else.** The `litmussdk` abstracts this.
- **Device status requires Prometheus metrics.** The DeviceHub GraphQL API does not expose run/stop state. `litmus_utils.get_device_running_state()` fetches and parses `/devicehub/metrics` for this.
- **Device property validation uses `list_device_by_id()`.** Scalar device properties (like `debug`, `alias_topics`) can be read back after a learner edits them by reloading the device object from the API. This is how `plc-01` and the archived `dh-03` validate learner changes.
- **Archived scenarios are excluded by subfolder placement.** `ScenarioEngine._load_all_scenario_classes()` uses `pkgutil.iter_modules()` which only scans the top-level `app/scenarios/` directory — subdirectories are not traversed.

---

## Troubleshooting the App

| Problem | Likely cause | Fix |
|---------|-------------|-----|
| "Litmus Edge connection failed" at startup | Wrong `EDGE_URL` or invalid credentials | Check `.env`; verify the OAuth2 token is active in Litmus Edge |
| `VALIDATE_CERTIFICATE` error | Self-signed cert | Set `VALIDATE_CERTIFICATE=false` in `.env` |
| Scenario setup fails | Litmus Edge API returned an error | Check Litmus Edge events log; ensure the token has admin permissions |
| Ticket still active after app restart | App lost in-memory state | Click **Force Reset All** in Admin Tools (bottom of the home page) |
| App won't start inside Litmus Marketplace | Docker deployment detected | Marketplace requires VM or ISO installation of Litmus Edge |
