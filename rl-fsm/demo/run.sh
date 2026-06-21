#!/usr/bin/env bash
# Side-by-side: fine-tuned Verifast DSL vs base Qwen Verilog.
# Usage:
#   ./run.sh                    # random task
#   ./run.sh task_0003          # specific task
#   ./run.sh ui                 # Streamlit dual-IDE
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-}"
for c in python3.12 python3.11 python3; do
  command -v "$c" >/dev/null 2>&1 || continue
  if "$c" -c 'import sys; exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
[[ -n "$PY" ]] || { echo "Need Python 3.10+"; exit 1; }

# Load HUD_API_KEY from BAA/.env or Verifast/.env if not set
if [[ -z "${HUD_API_KEY:-}" ]]; then
  for envfile in ../../BAA/.env ../.env ../../.env; do
    if [[ -f "$envfile" ]]; then set -a; source "$envfile"; set +a; break; fi
  done
fi
[[ -n "${HUD_API_KEY:-}" ]] || { echo "Set HUD_API_KEY"; exit 1; }

"$PY" -m pip install -q -r requirements.txt 2>/dev/null || true

if [[ "${1:-}" == "ui" ]]; then
  exec "$PY" -m streamlit run app.py
fi

if [[ "${1:-}" == "non-fsm" ]]; then
  shift
  exec "$PY" compare_non_fsm.py "$@"
fi

TASK_ARGS=()
[[ -n "${1:-}" && "${1}" != "ui" ]] && TASK_ARGS=(--task "$1")

exec "$PY" compare.py "${TASK_ARGS[@]}"
