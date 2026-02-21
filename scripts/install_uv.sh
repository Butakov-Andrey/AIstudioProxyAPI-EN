#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "[ERROR] uv is not installed. Install it first: https://docs.astral.sh/uv/"
  exit 1
fi

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "[ERROR] Python 3.9+ is required."
  exit 1
fi

echo "[INFO] Creating .venv with uv..."
uv venv --python "$PYTHON_BIN"

echo "[INFO] Installing dependencies with uv..."
uv pip install -r requirements-uv.txt

echo "[INFO] Installing Playwright Firefox..."
uv run playwright install firefox

echo "[INFO] Fetching Camoufox..."
uv run camoufox fetch

if [[ ! -f ".env" && -f ".env.example" ]]; then
  cp .env.example .env
  echo "[INFO] Created .env from .env.example"
fi

echo "[SUCCESS] UV setup complete."
echo "Next step:"
echo "  uv run python launch_camoufox.py --headless"
