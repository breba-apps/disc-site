#!/usr/bin/env bash
set -e  # stop on error

# Check if .venv exists
if [ ! -d ".venv" ]; then
  echo ".venv not found. Creating virtual environment..."
  python3 -m venv .venv
  echo "Installing requirements..."
  .venv/bin/pip install --upgrade pip
  if [ -f requirements.txt ]; then
    .venv/bin/pip install -r requirements.txt
  fi
fi

echo "Starting app..."
# Run app with uvicorn for auto-reload functionality
(
  cd breba_app
  PYTHONPATH=$(pwd)/.. ../.venv/bin/uvicorn main:app --host ${HOST:-0.0.0.0} --port ${PORT:-8080} --reload
)