#!/bin/bash
set -e
export HOME=/home/agent
export PATH=/root/utils/oss-cad-suite/bin:/usr/local/bin:/usr/bin:/bin
cd /home/agent/vt
echo "=== uv sync ==="
uv sync 2>&1 | tail -n 2
echo "=== cocotb_dv calibration (expect 0.25 / 1.0) ==="
uv run python tasks/stream_arb_fifo_cocotb_dv/scripts/check_calibration.py
echo "=== repair calibration (expect buggy 0.0 / golden 1.0 / latch 0.7) ==="
uv run python tasks/stream_arb_fifo_repair/scripts/check_calibration.py
echo "=== formal calibration (expect 0.35 / 1.0) ==="
uv run python tasks/stream_arb_fifo_formal/scripts/check_calibration.py
echo ALLCALDONE
