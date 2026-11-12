#!/bin/sh
# Startup command of the DemoBank container. Each step must succeed before
# the next one runs.
set -e

# One line per configuration problem and exit status 1 (no traceback).
python -m demobank.config

# exec: uvicorn replaces the shell, so it receives the stop signal itself.
exec uvicorn --factory demobank.app:create_app --host 0.0.0.0 --port 8100
