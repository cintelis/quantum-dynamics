#!/usr/bin/env bash
# Install GFN2-xTB (Grimme group) for vibration calculations.
# Uses the official `tblite` Python package from PyPI plus ASE (geometry optimisation + finite-difference
# frequencies). The standalone xtb binary from GitHub releases is an alternative, but its download server
# was timing out (HTTP 504) when this was set up.
set -euo pipefail
export PATH=$HOME/.local/bin:$PATH
uv pip install --python ~/cudaq-env/bin/python tblite ase
~/cudaq-env/bin/python - <<'EOF'
import tblite, ase
from tblite.ase import TBLite
from ase.build import molecule
m = molecule("H2O"); m.calc = TBLite(method="GFN2-xTB", verbosity=0)
print("tblite", getattr(tblite, "__version__", "?"), "| ase", ase.__version__, "| water energy (eV):", round(m.get_potential_energy(), 3))
EOF
