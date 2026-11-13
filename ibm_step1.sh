#!/usr/bin/env bash
# Step 1 (free, local): validate the IBM spin-chain circuit against the dashboard solver and ibm_fez noise.
cd "$(dirname "$0")"
export OPENBLAS_NUM_THREADS=${OPENBLAS_NUM_THREADS:-8} OMP_NUM_THREADS=${OMP_NUM_THREADS:-8}
exec ~/cudaq-env/bin/python -u -W ignore ibm/step1_validate.py "$@"
