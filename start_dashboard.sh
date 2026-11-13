#!/usr/bin/env bash
# Start the live dashboard (inside WSL). Open http://localhost:8765 in your Windows browser.
cd "$(dirname "$0")"
# WSL sees 22 threads but oversubscribing them made linear algebra ~10x slower; 8 is the sweet spot here.
export OPENBLAS_NUM_THREADS=${OPENBLAS_NUM_THREADS:-8} OMP_NUM_THREADS=${OMP_NUM_THREADS:-8}
exec ~/cudaq-env/bin/python -W ignore dashboard.py
