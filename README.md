# Litmus Lab

A hands-on troubleshooting trainer for **Litmus Edge 4.x**.

Litmus Lab is a Python web application that runs as a Docker container **inside** a Litmus Edge instance. It uses the official Litmus SDK to inject controlled, realistic problems into the live platform, then challenges learners to find and fix them using the real Litmus Edge UI.

---

## What It Does

| Step | Who does it | What happens |
|------|-------------|--------------|
| 1 | Learner | Picks a scenario from the Litmus Lab web UI |
| 2 | **Litmus Lab** | Calls the Litmus Edge API to create a broken state (stops a device, removes tags, etc.) |
| 3 | Learner | Switches to the Litmus Edge UI and investigates the problem |
| 4 | Learner | Clicks "Check My Solution" |
| 5 | **Litmus Lab** | Queries the API to verify the fix, reports pass or fail |
| 6 | **Litmus Lab** | Cleans up all resources it created |

---

## Scenarios (Phase 1)

| ID | Title | Category | Difficulty | What breaks |
|----|-------|----------|------------|-------------|
| `dh-01` | The Stopped Device | DeviceHub | Beginner | A device is stopped — appears in DeviceHub but publishes 0 messages |
| `dh-02` | The Tagless Device | DeviceHub | Beginner | A device is running but has zero tags configured |
| `dh-03` | The Silent Alias | DeviceHub | Intermediate | A device runs without alias topics, so flow subscriptions by name receive nothing |
| `sys-01` | The Locked-Out Engineer | System | Beginner | A user account has Viewer-only permissions and cannot modify DeviceHub |
| `sys-02` | The Dead Service | System | Intermediate | The analytics service (`loopedge-analytics2`) is stopped |

> ⚠️ **SYS-02 note:** This scenario stops a real platform service. If the app is restarted mid-scenario, use the **Force Reset All** button on the home page, or restart the service manually via *System > Device Management > Services* in Litmus Edge.

---

## Requirements

- **Litmus Edge 4.x** running on a VM or ISO install (not a Docker deployment — the Marketplace requires VM/ISO)
- **Docker** available on the machine where you will build and run this app
- A Litmus Edge **OAuth2 API token** with administrator-level permissions
- The **litmussdk wheel file** (`litmussdk-2.0.1-py3-none-any.whl`) placed in the `resources/` folder

---

## Setup

### 1. Get the Litmus SDK wheel

Obtain `litmussdk-2.0.1-py3-none-any.whl` from your Litmus contact or the [GitHub releases page](https://github.com/litmusautomation/litmus-sdk-releases) and place it at:

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

### 4. Build the Docker image

```bash
docker build -t litmus-lab .
```

This installs the SDK from the local wheel file and all other Python dependencies. It takes 1–2 minutes on the first build; subsequent builds are much faster because Docker caches the dependency layers.

### 5. Run the container

**Option A — Locally (for development and testing):**

```bash
docker run -p 8000:8000 --env-file .env litmus-lab
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

**Option B — Inside Litmus Edge via the Marketplace:**

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
│   ├── main.py                 # FastAPI routes and app entry point
│   ├── engine.py               # ScenarioEngine — manages scenario lifecycle
│   ├── litmus_utils.py         # Helper functions (Prometheus parsing, safe deletes)
│   ├── scenarios/
│   │   ├── __init__.py
│   │   ├── base.py             # BaseScenario abstract class (read this first!)
│   │   ├── dh_01_stopped_device.py
│   │   ├── dh_02_no_tags.py
│   │   ├── dh_03_alias_topics.py
│   │   ├── sys_01_permissions.py
│   │   └── sys_02_service_stopped.py
│   └── templates/
│       ├── base.html           # Shared HTML layout
│       ├── index.html          # Scenario list page
│       └── scenario.html       # Individual scenario page
├── resources/                  # NOT committed to git (see .gitignore)
│   └── litmussdk-2.0.1-py3-none-any.whl
├── .env.example                # Template for environment variables
├── .gitignore
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## Adding a New Scenario

1. Create a new file in `app/scenarios/`, e.g. `dh_04_my_scenario.py`.
2. Import and subclass `BaseScenario` from `scenarios.base`.
3. Set the class attributes (`id`, `title`, `category`, etc.).
4. Implement `setup()`, `validate()`, and `teardown()`.
5. That's it — the ScenarioEngine discovers it automatically at startup.

See `app/scenarios/base.py` for the full docstring explaining the contract, and any existing scenario file for a worked example.

---

## How the Code Is Organised

### `main.py`
The entry point. Defines HTTP routes (URL → function) and renders HTML pages. Think of it as the receptionist — it receives requests and sends them to the right place.

### `engine.py`
The brain. Manages which scenario is active, calls `setup()` / `validate()` / `teardown()`, handles the timeout, and holds the Litmus API connection. One instance lives for the lifetime of the app.

### `litmus_utils.py`
Helper functions that fill gaps in the SDK. Most importantly: `get_device_running_state()`, which reads Prometheus metrics to determine whether a device is running or stopped (this information is not available via the GraphQL API).

### `scenarios/base.py`
The contract. Every scenario must implement three methods. Read this file carefully before writing a new scenario — the comments explain every design decision.

### `scenarios/dh_01_*.py` … `sys_02_*.py`
The actual training content. Each file is one scenario, fully documented. The file-level docstring explains what the scenario teaches and how the setup/validation/teardown work.

---

## Architecture Notes

- **One scenario at a time.** Because scenarios modify live platform state, only one can be active at a time. Starting a second scenario while one is running returns an error.
- **All lab resources are prefixed `lab-`.** This makes them easy to identify in the Litmus Edge UI and ensures teardown never touches real production configuration.
- **The SDK uses GraphQL for DeviceHub, REST for everything else.** The `litmussdk` abstracts this — you don't need to think about it unless you're writing a new utility in `litmus_utils.py`.
- **Device status requires Prometheus metrics.** The DeviceHub GraphQL API does not expose run/stop state. `litmus_utils.get_device_running_state()` fetches and parses `/devicehub/metrics` for this information.

---

## Troubleshooting the App Itself

| Problem | Likely cause | Fix |
|---------|-------------|-----|
| App starts but "Litmus Edge connection failed" | Wrong `EDGE_URL` or invalid credentials | Check `.env` values; verify the OAuth2 token is active in Litmus Edge |
| `VALIDATE_CERTIFICATE` error | Self-signed cert | Set `VALIDATE_CERTIFICATE=false` in `.env` |
| Scenario setup fails | Litmus Edge API returned an error | Check Litmus Edge events log; ensure the token has admin permissions |
| SYS-02: analytics still stopped after app restart | App lost state during restart | Click **Force Reset All** on the home page |
| App won't start inside Litmus Marketplace | Docker deployment detected | Marketplace requires VM or ISO installation of Litmus Edge |
