#!/usr/bin/env bash
# One-time: add RDKit (molecular descriptors) to the CUDA-Q env for the materials explorer.
set -e
export PATH="$HOME/.local/bin:$PATH"
VIRTUAL_ENV=~/cudaq-env uv pip install -q rdkit
~/cudaq-env/bin/python -c 'import rdkit; print("rdkit", rdkit.__version__)'
