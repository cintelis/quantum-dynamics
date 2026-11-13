#!/usr/bin/env bash
# Generate new spacer molecules for custom synthesis -> data/new_molecules.json (needs data/explorer.json)
cd "$(dirname "$0")"
exec ~/cudaq-env/bin/python -W ignore materials/generate_molecules.py
