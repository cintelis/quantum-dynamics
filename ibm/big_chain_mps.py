"""
100-spin chain with a tensor-network (matrix product state, MPS) simulator: no quantum hardware needed.

Same model and circuit as step 1 (dashboard spin chain, J = 0.5 MHz, delta = 1, gamma = 0, Neel start, 0..1 us),
second-order Trotter steps of 25 ns. Here every step is the symmetric block even(dt/2) odd(dt) even(dt/2), so the
state is at an exact time after each step and one circuit can record <Z> of every spin every 2 steps (50 ns).
Each bond's RXX*RYY*RZZ is applied as one 4x4 unitary (one MPS truncation per bond).

The MPS keeps at most `chi` numbers per cut ("bond dimension"). Too small a chi throws away entanglement and the
answer drifts. Checks:
  24 spins: MPS at several chi vs the exact statevector simulation of the same circuit
  100 spins: MPS at chi = 64, 128, 256; the time where they disagree by > 0.01 marks the trust horizon

Output: data/ibm/chain100.json, output/chain100.png (staggered magnetisation) and output/chain100_heatmap.png (<Z> per spin)
"""
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

J, DELTA, T_MAX, DT = 0.5, 1.0, 1.0, 0.025
SNAP_EVERY = 2                               # record every 2 steps = 50 ns
N_STEPS = int(round(T_MAX / DT))
TIMES = np.round(np.arange(0, N_STEPS + 1, SNAP_EVERY) * DT, 4)


def bond_unitary(theta, delta):
    """exp(-i theta (XX + YY + delta ZZ)) as a 4x4 matrix (exact for one bond)."""
    from scipy.linalg import expm
    X = np.array([[0, 1], [1, 0]]); Y = np.array([[0, -1j], [1j, 0]]); Z = np.diag([1, -1])
    return expm(-1j * theta * (np.kron(X, X) + np.kron(Y, Y) + delta * np.kron(Z, Z)))


def chain_circuit(N):
    from qiskit import QuantumCircuit
    from qiskit.circuit.library import UnitaryGate
    from qiskit.quantum_info import Pauli
    th = 2 * np.pi * J * DT
    half, full = UnitaryGate(bond_unitary(th / 2, DELTA), label="half"), UnitaryGate(bond_unitary(th, DELTA), label="full")
    even = [(i, i + 1) for i in range(0, N - 1, 2)]
    odd = [(i, i + 1) for i in range(1, N - 1, 2)]
    qc = QuantumCircuit(N)
    for i in range(1, N, 2):
        qc.x(i)

    def snap(k):
        for i in range(N):
            qc.save_expectation_value(Pauli("Z"), [i], label=f"z{i}_t{k}")

    snap(0)
    for s in range(1, N_STEPS + 1):
        for i, j in even:
            qc.append(half, [i, j])
        for i, j in odd:
            qc.append(full, [i, j])
        for i, j in even:
            qc.append(half, [i, j])
        if s % SNAP_EVERY == 0:
            snap(s)
    return qc


def run(N, method, chi=None):
    from qiskit_aer import AerSimulator
    opts = dict(method=method, max_parallel_threads=8)
    if method == "matrix_product_state":
        # Aer's memory pre-check assumes an uncompressed state (2^N amplitudes) and ignores the chi cap, so it refuses
        # 100 qubits. The real MPS needs ~N * chi^2 * 16 bytes (about 100 MB at chi = 256): lift the pre-check.
        opts.update(matrix_product_state_max_bond_dimension=chi, matrix_product_state_truncation_threshold=1e-10,
                    mps_omp_threads=8, max_memory_mb=2 ** 40)
    sim = AerSimulator(**opts)
    qc = chain_circuit(N)
    t0 = time.time()
    data = sim.run(qc, shots=1).result().data(0)
    secs = time.time() - t0
    Zt = np.array([[float(np.real(data[f"z{i}_t{s}"])) for i in range(N)]
                   for s in range(0, N_STEPS + 1, SNAP_EVERY)])            # [time, site]
    stag = (Zt * np.array([(-1) ** i for i in range(N)])).mean(axis=1)
    return dict(Z=Zt, stag=stag, seconds=round(secs, 1))


def main():
    out = dict(model=dict(J_MHz=J, delta=DELTA, gamma=0.0, t_max_us=T_MAX, dt_us=DT, times_us=TIMES.tolist(),
                          method="Qiskit Aer matrix_product_state, 2nd-order Trotter, one 4x4 unitary per bond"))
    # 1) accuracy check at 24 spins against the exact statevector simulation of the same circuit
    ref = run(24, "statevector")
    chk = {}
    for chi in (16, 32, 64, 128):
        r = run(24, "matrix_product_state", chi)
        chk[chi] = dict(max_error_stag=float(np.max(np.abs(r["stag"] - ref["stag"]))),
                        max_error_any_site=float(np.max(np.abs(r["Z"] - ref["Z"]))), seconds=r["seconds"])
        print(f"24 spins  chi {chi:4d}: max error staggered {chk[chi]['max_error_stag']:.2e}, any site "
              f"{chk[chi]['max_error_any_site']:.2e}  ({r['seconds']} s; exact statevector {ref['seconds']} s)", flush=True)
    out["check_24"] = dict(statevector_seconds=ref["seconds"], mps=chk, stag_exact=ref["stag"].tolist())

    # 2) 100 spins at increasing bond dimension
    runs = {}
    for chi in (64, 128, 256):
        runs[chi] = run(100, "matrix_product_state", chi)
        print(f"100 spins chi {chi:4d}: {runs[chi]['seconds']} s, staggered at 1 us {runs[chi]['stag'][-1]:+.4f}", flush=True)
    best, prev = runs[256], runs[128]
    diff = np.abs(best["stag"] - prev["stag"])
    bad = np.where(diff > 0.01)[0]
    horizon = float(TIMES[bad[0]]) if len(bad) else T_MAX
    print(f"chi 128 vs 256: max diff {diff.max():.2e}; trusted to {horizon} us", flush=True)
    out["chain_100"] = dict(trusted_until_us=horizon, max_diff_128_vs_256=float(diff.max()),
                            runs={chi: dict(seconds=r["seconds"], stag=r["stag"].tolist()) for chi, r in runs.items()},
                            Z_chi256=best["Z"].tolist())
    # finite-size comparison with step 1's exact 6/9-spin curves (same model; step-1 grid differs, so interpolate)
    s1p = os.path.join(ROOT, "data", "ibm", "step1.json")
    if os.path.exists(s1p):
        s1 = json.load(open(s1p))
        t1 = np.linspace(0, T_MAX, 21)
        out["small_exact"] = {N: np.interp(TIMES, t1, s1["sizes"][str(N)]["series"]["staggered magnetisation"]["exact"]).tolist()
                              for N in (6, 9)}
    out["stag_24_exact"] = ref["stag"].tolist()
    os.makedirs(os.path.join(ROOT, "data", "ibm"), exist_ok=True)
    json.dump(out, open(os.path.join(ROOT, "data", "ibm", "chain100.json"), "w"), indent=1)
    charts(out)
    print("wrote data/ibm/chain100.json, output/chain100.png, output/chain100_heatmap.png")


def charts(out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    bg, ink, muted, grid = "#141414", "#e8e8e8", "#9a9a9a", "#2a2a2a"
    T = np.array(out["model"]["times_us"])
    fig, ax = plt.subplots(figsize=(9, 4.2), facecolor=bg); ax.set_facecolor(bg)
    series = [("100 spins (MPS, χ = 256)", out["chain_100"]["runs"][256]["stag"], "#6aa800", "-"),
              ("24 spins (exact)", out["stag_24_exact"], "#3987e5", "-")]
    if "small_exact" in out:
        series += [("9 spins (exact)", out["small_exact"][9], "#d95926", "-"), ("6 spins (exact)", out["small_exact"][6], "#9085e9", "-")]
    for name, y, c, ls in series:
        ax.plot(T, y, ls, color=c, lw=2, label=name)
        ax.annotate(name.split(" (")[0], (T[-1], y[-1]), xytext=(6, 0), textcoords="offset points", color=ink, fontsize=8.5, va="center")
    h = out["chain_100"]["trusted_until_us"]
    if h < T[-1]:
        ax.axvspan(h, T[-1], color="#ffffff", alpha=0.05, lw=0)
        ax.text(h + 0.01, 0.92, "χ-limited: less certain", color=muted, fontsize=8)
    ax.axhline(0, color=grid, lw=1)
    ax.set_title("Staggered magnetisation: how chain length changes the dynamics", color=ink, fontsize=11, loc="left")
    ax.set_xlabel("time (µs)", color=muted); ax.tick_params(colors=muted); ax.grid(color=grid, lw=0.6)
    ax.set_xlim(0, T[-1] * 1.12)
    for s in ax.spines.values():
        s.set_visible(False)
    leg = ax.legend(loc="upper right", frameon=False, fontsize=8.5, bbox_to_anchor=(0.88, 1))
    for t in leg.get_texts():
        t.set_color(ink)
    fig.tight_layout(); fig.savefig(os.path.join(ROOT, "output", "chain100.png"), dpi=150, facecolor=bg)

    Z = np.array(out["chain_100"]["Z_chi256"])
    cmap = LinearSegmentedColormap.from_list("div", ["#3987e5", "#2a2a2a", "#6aa800"])     # blue = down, gray = 0, green = up
    fig, ax = plt.subplots(figsize=(9, 3.6), facecolor=bg); ax.set_facecolor(bg)
    im = ax.imshow(Z.T, aspect="auto", origin="lower", cmap=cmap, vmin=-1, vmax=1,
                   extent=[T[0] - 0.025, T[-1] + 0.025, -0.5, Z.shape[1] - 0.5], interpolation="nearest")
    ax.set_title("<Z> of every spin, 100-spin chain · green = up (+1), blue = down (−1)", color=ink, fontsize=11, loc="left")
    ax.set_xlabel("time (µs)", color=muted); ax.set_ylabel("spin", color=muted); ax.tick_params(colors=muted)
    for s in ax.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01); cb.ax.tick_params(colors=muted); cb.outline.set_visible(False)
    fig.tight_layout(); fig.savefig(os.path.join(ROOT, "output", "chain100_heatmap.png"), dpi=150, facecolor=bg)


if __name__ == "__main__":
    main()
