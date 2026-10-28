#!/usr/bin/env bash
# Developer helper for macOS/Linux.
#
#   packaging/build_local.sh            # setup + test + run (default)
#   packaging/build_local.sh setup      # create .venv and install requirements
#   packaging/build_local.sh test       # run tests (if tests/ exists)
#   packaging/build_local.sh run        # start the app (python -m app)
#   packaging/build_local.sh launcher   # start via packaging/launcher.py (like the .exe)
#   packaging/build_local.sh package    # PyInstaller build for THIS OS (sanity check only;
#                                       # the Windows installer is built by GitHub Actions)
#   packaging/build_local.sh docker     # docker compose up --build
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
VENV="$ROOT/.venv"
PY="${PYTHON:-python3}"
export OUTREACH_DATA_DIR="${OUTREACH_DATA_DIR:-$ROOT/.devdata}"

setup() {
  if [[ ! -x "$VENV/bin/python" ]]; then
    echo ">> Creating virtualenv in .venv"
    "$PY" -m venv "$VENV"
  fi
  "$VENV/bin/python" -m pip install --quiet --upgrade pip
  "$VENV/bin/python" -m pip install --quiet -r requirements.txt pytest
  echo ">> Dependencies installed"
}

run_tests() {
  if [[ -d tests ]]; then
    echo ">> Running tests"
    "$VENV/bin/python" -m pytest -q tests
  else
    echo ">> No tests/ folder, skipping tests"
  fi
}

run_app() {
  echo ">> Starting Lead Outreach (data in $OUTREACH_DATA_DIR, port ${OUTREACH_PORT:-8765}). Ctrl+C to stop."
  exec "$VENV/bin/python" -m app
}

run_launcher() {
  exec "$VENV/bin/python" packaging/launcher.py
}

package() {
  "$VENV/bin/python" -m pip install --quiet pyinstaller pillow
  "$VENV/bin/python" packaging/make_icon.py
  "$VENV/bin/pyinstaller" packaging/lead_outreach.spec --noconfirm --clean \
    --distpath dist --workpath build/pyinstaller
  echo ">> Built: dist/Lead Outreach/"
}

docker_up() {
  docker compose up -d --build
  echo ">> Open http://127.0.0.1:8765  (stop with: docker compose down)"
}

cmd="${1:-all}"
case "$cmd" in
  setup)    setup ;;
  test)     setup; run_tests ;;
  run)      setup; run_app ;;
  launcher) setup; run_launcher ;;
  package)  setup; run_tests; package ;;
  docker)   docker_up ;;
  all)      setup; run_tests; run_app ;;
  *) echo "Unknown command: $cmd (use setup|test|run|launcher|package|docker)"; exit 1 ;;
esac
