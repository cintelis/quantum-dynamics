"""
Spin chain (Heisenberg XXZ) as a Qiskit circuit, ready for an IBM quantum computer.

Same physics as the dashboard's spin chain (sim.model_spinchain):
    H = 2*pi*J * sum_i (X_i X_{i+1} + Y_i Y_{i+1} + delta * Z_i Z_{i+1})      J in MHz, t in microseconds
    start in the Neel state |0101...>  (even sites up, Z = +1; odd sites down, Z = -1)
    observables: staggered magnetisation (1/N) sum_i (-1)^i Z_i, <Z> of spin 0 and of spin N//2

On a gate-based quantum computer the smooth time evolution is sliced into Trotter steps of length dt.
For a single pair of neighbours XX, YY and ZZ commute, so each bond's evolution is exact:
    exp(-i theta (XX + YY + delta ZZ)) = RXX(2 theta) RYY(2 theta) RZZ(2 delta theta),  theta = 2*pi*J*dt
Bonds on even and odd links don't commute; a second-order (symmetric) split keeps the error ~ dt^3 per step:
    [even(dt/2) odd(dt) even(dt/2)]^n, with neighbouring even halves merged.
Dephasing (gamma) is NOT a circuit setting: on hardware the chip's own noise plays that role. Use gamma = 0.
"""
import numpy as np
from qiskit import QuantumCircuit
from qiskit.quantum_info import SparsePauliOp

TWO_PI = 2 * np.pi


def bond(qc, i, j, theta, delta):
    qc.rxx(2 * theta, i, j)
    qc.ryy(2 * theta, i, j)
    qc.rzz(2 * delta * theta, i, j)


def trotter_circuit(N, J, delta, t, n_steps):
    """Circuit that prepares the Neel state and evolves it to time t (us) in n_steps second-order steps."""
    qc = QuantumCircuit(N)
    for i in range(1, N, 2):
        qc.x(i)
    if n_steps == 0 or t == 0:
        return qc
    th = TWO_PI * J * t / n_steps
    even = [(i, i + 1) for i in range(0, N - 1, 2)]
    odd = [(i, i + 1) for i in range(1, N - 1, 2)]
    for i, j in even:
        bond(qc, i, j, th / 2, delta)
    for k in range(n_steps):
        for i, j in odd:
            bond(qc, i, j, th, delta)
        last = k == n_steps - 1
        for i, j in even:
            bond(qc, i, j, th / 2 if last else th, delta)
    return qc


def observables(N):
    stag = SparsePauliOp.from_sparse_list([("Z", [i], (-1) ** i / N) for i in range(N)], num_qubits=N)
    z0 = SparsePauliOp.from_sparse_list([("Z", [0], 1.0)], num_qubits=N)
    zm = SparsePauliOp.from_sparse_list([("Z", [N // 2], 1.0)], num_qubits=N)
    return {"staggered magnetisation": stag, "spin 0 <Z>": z0, f"spin {N // 2} <Z>": zm}


def steps_for(t, dt):
    return int(np.ceil(t / dt - 1e-9)) if t > 0 else 0
