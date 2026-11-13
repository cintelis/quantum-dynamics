#!/usr/bin/env bash
# GFN2-xTB vibration spectra for round-1 + top new spacers -> data/vibrations.json (needs setup_xtb.sh)
cd "$(dirname "$0")"
exec ~/cudaq-env/bin/python -u -W ignore materials/vibrations.py "$@"
