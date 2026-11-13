#!/usr/bin/env bash
# 100-spin chain with a matrix-product-state simulator (free, local). See ibm/big_chain_mps.py.
cd "$(dirname "$0")"
export OPENBLAS_NUM_THREADS=${OPENBLAS_NUM_THREADS:-8} OMP_NUM_THREADS=${OMP_NUM_THREADS:-8}
exec ~/cudaq-env/bin/python -u -W ignore ibm/big_chain_mps.py "$@"
