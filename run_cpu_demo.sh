#!/usr/bin/env bash
# Run the demo simulations on CPU inside WSL. Results land in ./output
cd "$(dirname "$0")"
PY=~/cudaq-env/bin/python
$PY -W ignore sim.py --model cavity
$PY -W ignore sim.py --model spinchain --spins 6 --gamma 0.05
$PY -W ignore sim.py --model spinchain --spins 8 --gamma 0.05
