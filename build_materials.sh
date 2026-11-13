#!/usr/bin/env bash
# Rebuild data/explorer.json (run data/catalogue.json export on Windows first: python materials\fetch_catalogue.py)
cd "$(dirname "$0")"
exec ~/cudaq-env/bin/python -W ignore materials/build_explorer.py
