#!/usr/bin/env bash
# One-time setup: CUDA-Q in a Python env inside WSL Ubuntu (no sudo needed).
set -e
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
rm -rf ~/cudaq-env
uv venv -q -p 3.12 ~/cudaq-env
VIRTUAL_ENV=~/cudaq-env uv pip install -q cudaq matplotlib
~/cudaq-env/bin/python -c 'import cudaq; print("cudaq", cudaq.__version__); print([t.name for t in cudaq.get_targets()])'
