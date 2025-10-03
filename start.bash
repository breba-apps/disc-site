#!/usr/bin/env bash
set -e  # stop on error

uv sync

echo "Starting app..."
# Run app with project root in PYTHONPATH
PYTHONPATH=. CHAINLIT_APP_ROOT=./breba_app uv run breba_app/main.py
