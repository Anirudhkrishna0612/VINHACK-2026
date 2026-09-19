#!/usr/bin/env bash
cd "$(dirname "$0")/ai-engine" && { [ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }; } && . .venv/bin/activate && exec python main.py
