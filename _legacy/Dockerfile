# Dockerfile — builds the Litmus Lab container image.
#
# HOW DOCKER BUILDS WORK (plain-language summary):
# A Dockerfile is a recipe. Each line starting with a keyword (FROM, RUN, COPY…)
# adds a "layer" to the image. Docker caches each layer, so if a line hasn't
# changed since the last build, it reuses the cached result instead of re-running
# it. This makes builds faster.
#
# The general strategy here is:
#   1. Start from a minimal official Python 3.12 image.
#   2. Install Python dependencies (slow step, cached after first build).
#   3. Copy the application source code (fast, changes frequently).
#   4. Set the startup command.
#
# WHY python:3.12-slim?
#   'slim' is a stripped-down version of the official Python image with fewer
#   tools pre-installed. It produces a smaller final image, which is important
#   when distributing via the Litmus Marketplace.
#
# NETWORK ACCESS:
#   This container calls the Litmus Edge REST API. The EDGE_URL environment
#   variable must point to the Litmus Edge device's IP or hostname as seen
#   from inside the container. If you run with --network host, use:
#     EDGE_URL=https://localhost
#   If you run with the default bridge network, use the device's LAN IP:
#     EDGE_URL=https://192.168.1.x
#   Certificate validation is typically disabled for Litmus Edge dev instances
#   (self-signed cert) via VALIDATE_CERTIFICATE=false.

# ── Stage: base image ────────────────────────────────────────────────────────
FROM python:3.12-slim

# Set the working directory inside the container.
# All subsequent COPY and RUN commands are relative to this path.
WORKDIR /app

# ── Install the Litmus SDK from the local wheel file ────────────────────────
# We copy the wheel into a temporary location and install it before copying
# the rest of the app code. This keeps the SDK installation in its own layer,
# so it is only re-run when the wheel file changes (rarely).
#
# --no-cache-dir tells pip not to cache downloaded packages, keeping the
# image size smaller.
COPY resources/litmussdk-2.0.1-py3-none-any.whl /tmp/litmussdk-2.0.1-py3-none-any.whl
RUN pip install --no-cache-dir /tmp/litmussdk-2.0.1-py3-none-any.whl && rm /tmp/litmussdk-2.0.1-py3-none-any.whl

# ── Install Python dependencies ──────────────────────────────────────────────
# We copy requirements.txt first (separate from app code) so that Docker can
# cache this layer. If only app code changes but requirements don't, this
# layer is reused and the slow `pip install` step is skipped.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Copy application source code ─────────────────────────────────────────────
# This is the last COPY so that code changes don't invalidate the dependency
# layers above.
COPY app/ .

# ── Expose the port the app listens on ───────────────────────────────────────
# EXPOSE is documentation — it does not actually publish the port. You still
# need to use -p 8000:8000 (or Litmus Marketplace port mapping) at runtime.
EXPOSE 8000

# ── Health check ─────────────────────────────────────────────────────────────
# Docker (and Litmus Edge's Marketplace) can poll this endpoint to know if the
# container is healthy. If /health returns non-200, Docker marks it unhealthy.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# ── Startup command ───────────────────────────────────────────────────────────
# uvicorn runs the FastAPI app.
#   main:app  → the 'app' object inside 'main.py'
#   --host 0.0.0.0  → listen on all network interfaces (required inside Docker)
#   --port 8000     → the port EXPOSE'd above
#   --workers 1     → single worker; multiple workers would create multiple
#                     ScenarioEngine instances with separate state, which would
#                     break the "one active scenario at a time" guarantee.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
