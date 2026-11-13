#!/usr/bin/env bash
# Install Qiskit (IBM's quantum SDK), the Aer simulator and the IBM Runtime client into ~/cudaq-env.
# qiskit-ibm-runtime also ships offline "fake" IBM backends with real calibration data (noise preview, no account).
set -euo pipefail
export PATH=$HOME/.local/bin:$PATH
uv pip install --python ~/cudaq-env/bin/python qiskit qiskit-aer qiskit-ibm-runtime
~/cudaq-env/bin/python - <<'EOF'
import qiskit, qiskit_aer, qiskit_ibm_runtime
from qiskit_ibm_runtime.fake_provider import FakeFez
b = FakeFez()
print("qiskit", qiskit.__version__, "| aer", qiskit_aer.__version__, "| ibm-runtime", qiskit_ibm_runtime.__version__,
      "| offline backend", b.name, b.num_qubits, "qubits")
EOF
