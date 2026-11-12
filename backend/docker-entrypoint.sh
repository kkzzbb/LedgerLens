#!/bin/sh
# Startup command of the backend container. Each step must succeed before
# the next one runs.
set -e

# One line per configuration problem and exit status 1 (no traceback).
python -m ledgerlens.config

# Only the backend container migrates; the worker reuses the image without
# this step.
alembic upgrade head

# exec: uvicorn replaces the shell, so it receives the stop signal itself.
exec uvicorn --factory ledgerlens.api.app:create_app --host 0.0.0.0 --port 8000
