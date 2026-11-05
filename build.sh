#!/usr/bin/env bash
# Build a single-file QuantiSheet executable into dist/ (macOS / Linux).
set -euo pipefail
cd "$(dirname "$0")"

PY=${PY:-python3}
VENV=${VENV:-.venv}

echo "== creating venv =="
$PY -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "== installing =="
python -m pip install --upgrade pip wheel
pip install -r requirements.txt
pip install "pyinstaller>=6.3,<7" pytest

echo "== testing =="
QT_QPA_PLATFORM=offscreen python -m pytest -q

echo "== building =="
pyinstaller --clean --noconfirm quantisheet.spec

echo "== done =="
ls -lh dist/
