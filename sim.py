"""
Build-your-own quantum dynamics simulation with CUDA-Q.

Same idea as NVIDIA's "Accelerating Google's QPU development" blog:
describe a quantum device with operators, add noise, and watch it evolve in time.

The model is defined ONCE with CUDA-Q operators. It then runs on either:
  --backend cpu  : converts the operators to matrices and solves the
                   Lindblad master equation with SciPy (works on any laptop)
  --backend gpu  : hands the same operators to cudaq.evolve on the
                   "dynamics" target (needs an NVIDIA GPU, e.g. Colab / Brev)

Models:
  cavity    : superconducting qubit coupled to a readout resonator
              (dispersive readout - how Google-style chips measure qubits)
  spinchain : chain of N interacting spins (the blog's benchmark system)

Examples:
  python sim.py --model cavity
  python sim.py --model spinchain --spins 6 --gamma 0.05
  python sim.py --model spinchain --spins 14 --backend gpu
"""
import argparse
import csv
import math
import os
import time

import numpy as np
import cudaq
from cudaq import spin, boson

TWO_PI = 2 * np.pi


# ---------------------------------------------------------------- models
# Each model returns: H, dims, collapse_ops, observables (name -> op), psi0, times
# Units: frequencies in MHz (times 2*pi), time in microseconds.

def model_cavity(a):
    """Qubit (degree 0) + resonator with `levels` photon levels (degree 1).

    Dispersive Hamiltonian in the rotating frame:  H = (chi/2) * Z * a^dag a
    The resonator's frequency shifts depending on the qubit state, so a
    coherent pulse in the resonator splits in two. Photons leaking out
    (kappa) carry that information away and destroy the qubit's
    superposition - "measurement-induced dephasing".
    """
    chi, kappa, alpha = TWO_PI * a.chi, TWO_PI * a.kappa, a.alpha
    dims = {0: 2, 1: a.levels}
    # Identity "padding" so every operator spans both degrees (CPU path needs full matrices).
    # Use the generic identity: in CUDA-Q 0.16, spin.i(0) * <boson op> corrupts global state
    # and every later to_matrix() fails with "dimension for spin operator must be 2".
    q_id = lambda: cudaq.operators.identity(0)
    c_id = lambda: cudaq.operators.identity(1)

    H = (chi / 2) * spin.z(0) * boson.number(1)
    c_ops = [np.sqrt(kappa) * q_id() * boson.annihilate(1)]
    obs = {
        "photons <n>": q_id() * boson.number(1),
        "cavity X quadrature": q_id() * (boson.annihilate(1) + boson.create(1)),
        "qubit coherence <X>": spin.x(0) * c_id(),
        "qubit <Z>": spin.z(0) * c_id(),
    }

    # Initial state: qubit in |+> = (|0>+|1>)/sqrt2, cavity in coherent state |alpha>.
    # Read the basis ordering from the operators themselves (no convention guessing).
    zdiag = np.real(np.diag((spin.z(0) * c_id()).to_matrix(dims)))
    ndiag = np.rint(np.real(np.diag((q_id() * boson.number(1)).to_matrix(dims)))).astype(int)
    coh = np.array([np.exp(-abs(alpha) ** 2 / 2) * alpha ** k / np.sqrt(float(math.factorial(k)))
                    for k in range(a.levels)], dtype=complex)
    psi0 = np.array([coh[n] / np.sqrt(2) for z, n in zip(zdiag, ndiag)], dtype=complex)
    psi0 /= np.linalg.norm(psi0)

    times = np.linspace(0, a.t_max, a.steps)
    return H, dims, c_ops, obs, psi0, times


def model_spinchain(a):
    """N spins in a line, Heisenberg XXZ coupling, optional dephasing noise.

    H = J * sum_i (X_i X_{i+1} + Y_i Y_{i+1} + delta * Z_i Z_{i+1})
    Starts in the Neel state |0101...> and tracks how the ordering melts.
    """
    N, J, delta = a.spins, TWO_PI * a.J, a.delta
    dims = {i: 2 for i in range(N)}
    def ident():
        op = spin.i(0)
        for i in range(1, N):
            op = op * spin.i(i)
        return op

    H = 0 * ident()
    for i in range(N - 1):
        H += J * (spin.x(i) * spin.x(i + 1) + spin.y(i) * spin.y(i + 1)
                  + delta * spin.z(i) * spin.z(i + 1))
    H = H * ident()  # make sure every degree is present

    c_ops = ([np.sqrt(TWO_PI * a.gamma) * spin.z(i) * ident() for i in range(N)]
             if a.gamma > 0 else [])

    stag = 0 * ident()
    for i in range(N):
        stag += ((-1) ** i / N) * spin.z(i)
    obs = {
        "staggered magnetisation": stag * ident(),
        "spin 0 <Z>": spin.z(0) * ident(),
        f"spin {N // 2} <Z>": spin.z(N // 2) * ident(),
    }

    # Neel state: find the basis index where Z_i = +1 for even i, -1 for odd i.
    want = np.array([1 if i % 2 == 0 else -1 for i in range(N)])
    zd = np.array([np.real(np.diag((spin.z(i) * ident()).to_matrix(dims))) for i in range(N)])
    idx = int(np.where((zd.T == want).all(axis=1))[0][0])
    psi0 = np.zeros(2 ** N, dtype=complex)
    psi0[idx] = 1.0

    times = np.linspace(0, a.t_max, a.steps)
    return H, dims, c_ops, obs, psi0, times


import transmon  # noqa: E402  (Koch et al. 2007 transmon; CPU-only, tiny system)

import funnel  # noqa: E402  (quasi-2D perovskite energy funnel; CPU-only)

MODELS = {"cavity": model_cavity, "spinchain": model_spinchain, "transmon": transmon.model, "funnel": funnel.model}


def profile_for(model, a, dims):
    """A per-index view over time, drawn as a heatmap by the dashboard.
    Returns (title, row_labels, diag_matrix [rows x D], kind, ops) where kind is
    'sequential' (0..1) or 'diverging' (-1..1) and ops (or None) lets the GPU path
    measure the same rows as observables."""
    if model == "transmon":
        return transmon.profile(a)
    if model == "funnel":
        return funnel.profile(a)
    if model == "cavity":
        ndiag = np.rint(np.real(np.diag(
            (cudaq.operators.identity(0) * boson.number(1)).to_matrix(dims)))).astype(int)
        rows = np.array([(ndiag == n).astype(float) for n in range(a.levels)])
        return "Photon-number distribution P(n)", [f"n={n}" for n in range(a.levels)], rows, "sequential", None
    N = a.spins
    def ident():
        op = spin.i(0)
        for i in range(1, N):
            op = op * spin.i(i)
        return op
    ops = [spin.z(i) * ident() for i in range(N)]
    rows = np.array([np.real(np.diag(op.to_matrix(dims))) for op in ops])
    return "Spin <Z> per site", [f"spin {i}" for i in range(N)], rows, "diverging", ops


# ---------------------------------------------------------------- backends

def build_lindblad(H, dims, c_ops):
    """Return (rhs, d) for the Lindblad master equation
    d rho/dt = -i[H,rho] + sum L rho L^+ - 1/2{L^+L, rho}, with rho flattened row-major."""
    Hm = H.to_matrix(dims)
    Ls = [c.to_matrix(dims) for c in c_ops]
    LdL = sum((L.conj().T @ L for L in Ls), np.zeros_like(Hm))
    Heff = Hm - 0.5j * LdL  # non-Hermitian effective Hamiltonian
    d = Hm.shape[0]

    if d <= 512:
        # Build the Liouvillian once as a sparse d^2 x d^2 matrix; each step is one sparse mat-vec.
        # Row-major vec: vec(A rho B) = kron(A, B^T) vec(rho)
        import scipy.sparse as sp
        I = sp.identity(d, format="csr")
        He = sp.csr_matrix(Heff)
        Liou = -1j * (sp.kron(He, I) - sp.kron(I, He.conj()))
        for L in Ls:
            Ls_ = sp.csr_matrix(L)
            Liou = Liou + sp.kron(Ls_, Ls_.conj())
        Liou = Liou.tocsr()

        def rhs(_t, y):
            return Liou @ y
    else:
        # Bigger system: never form d^2 x d^2, work with rho directly.
        def rhs(_t, y):
            rho = y.reshape(d, d)
            out = -1j * (Heff @ rho - rho @ Heff.conj().T)
            for L in Ls:
                out += L @ rho @ L.conj().T
            return out.ravel()
    return rhs, d


def run_cpu(H, dims, c_ops, obs, psi0, times):
    """Whole run in one go (used by the command line)."""
    from scipy.integrate import solve_ivp

    rhs, d = build_lindblad(H, dims, c_ops)
    rho0 = psi0 if np.ndim(psi0) == 2 else np.outer(psi0, psi0.conj())  # a model may start mixed
    sol = solve_ivp(rhs, (times[0], times[-1]), rho0.ravel(), t_eval=times,
                    method="DOP853", rtol=1e-7, atol=1e-9)
    if not sol.success:
        raise RuntimeError(sol.message)
    Om = {k: v.to_matrix(dims) for k, v in obs.items()}
    rhos = sol.y.T.reshape(len(times), d, d)
    return {k: np.real(np.einsum("ij,tji->t", M, rhos)) for k, M in Om.items()}


def stream_cpu(H, dims, c_ops, obs, psi0, times, profile_diags=None):
    """Step-by-step run (used by the dashboard). Yields one dict per time point:
    {"i", "t", "obs": [...], "profile": [...], "purity"} as soon as it is solved."""
    from scipy.integrate import complex_ode

    rhs, d = build_lindblad(H, dims, c_ops)
    Om = [v.to_matrix(dims) for v in obs.values()]
    P = np.asarray(profile_diags) if profile_diags is not None else None

    def measure(i, t, y):
        rho = y.reshape(d, d)
        return {
            "i": i, "t": float(t),
            "obs": [float(np.real(np.sum(M * rho.T))) for M in Om],     # Tr(M rho)
            "profile": (P @ np.real(np.diag(rho))).tolist() if P is not None else [],
            "purity": float(np.real(np.vdot(rho, rho))),                # Tr(rho^2): 1 = pure
        }

    rho0 = (psi0 if np.ndim(psi0) == 2 else np.outer(psi0, psi0.conj())).astype(complex).ravel()
    yield measure(0, times[0], rho0)
    r = complex_ode(rhs).set_integrator("dopri5", rtol=1e-7, atol=1e-9, nsteps=1_000_000)
    r.set_initial_value(rho0, times[0])
    for i, t in enumerate(times[1:], start=1):
        y = r.integrate(t)
        if not r.successful():
            raise RuntimeError(f"integrator failed at t={t:.4f}")
        yield measure(i, t, y)


def run_gpu(H, dims, c_ops, obs, psi0, times):
    """Same model on NVIDIA's GPU dynamics solver (cuDensityMat)."""
    cudaq.set_target("dynamics")
    names = list(obs)
    result = cudaq.evolve(
        H, dims,
        cudaq.Schedule(times, ["t"]),
        cudaq.State.from_data(psi0.astype(np.complex128)),
        collapse_operators=c_ops,
        observables=[obs[k] for k in names],
        store_intermediate_results=cudaq.IntermediateResultSave.EXPECTATION_VALUE,
        integrator=cudaq.RungeKuttaIntegrator(),
    )
    vals = np.array([[e.expectation() for e in step] for step in result.expectation_values()])
    return {k: np.real(vals[:, i]) for i, k in enumerate(names)}


def stream_gpu(H, dims, c_ops, obs, psi0, times, extra_obs=None, chunk=10):
    """GPU run in short time chunks so the dashboard sees progress live.
    Each chunk continues from the previous chunk's final state. Falls back to one
    single evolve call if chunking is not supported. Yields the same dicts as stream_cpu."""
    cudaq.set_target("dynamics")
    names = list(obs)
    ops = [obs[k] for k in names] + list(extra_obs or [])
    n_obs = len(names)

    def evolve(seg, state):
        return cudaq.evolve(
            H, dims, cudaq.Schedule(seg, ["t"]), state,
            collapse_operators=c_ops, observables=ops,
            store_intermediate_results=cudaq.IntermediateResultSave.EXPECTATION_VALUE,
            integrator=cudaq.RungeKuttaIntegrator(),
        )

    def rows(res, seg, offset, skip_first):
        vals = [[e.expectation() for e in step] for step in res.expectation_values()]
        for j in range(1 if skip_first else 0, len(seg)):
            v = np.real(np.array(vals[j]))
            yield {"i": offset + j, "t": float(seg[j]), "obs": v[:n_obs].tolist(),
                   "profile": v[n_obs:].tolist(), "purity": None}

    state = cudaq.State.from_data(psi0.astype(np.complex128))
    done = 0  # index of the last time point already yielded (+1)
    try:
        i = 0
        while i < len(times) - 1:
            seg = times[i:i + chunk + 1]
            res = evolve(seg, state)
            for row in rows(res, seg, i, skip_first=i > 0):
                done = row["i"] + 1
                yield row
            state = res.final_state()
            i += len(seg) - 1
    except Exception:
        if done > chunk + 1:
            raise  # chunking worked before, so this is a real error
        res = evolve(times, cudaq.State.from_data(psi0.astype(np.complex128)))
        for row in rows(res, times, 0, skip_first=False):
            if row["i"] >= done:
                yield row


# ---------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", choices=MODELS, default="cavity")
    p.add_argument("--backend", choices=["cpu", "gpu", "both"], default="cpu",
                   help="both = run CPU and GPU and check they agree")
    p.add_argument("--t-max", type=float, default=3.0, help="end time, microseconds")
    p.add_argument("--steps", type=int, default=301)
    # cavity knobs
    p.add_argument("--levels", type=int, default=15, help="photon levels kept in the resonator")
    p.add_argument("--chi", type=float, default=1.0, help="dispersive shift, MHz")
    p.add_argument("--kappa", type=float, default=0.3, help="resonator leak rate, MHz")
    p.add_argument("--alpha", type=float, default=2.0, help="coherent-state amplitude (sqrt of photons)")
    # spin-chain knobs
    p.add_argument("--spins", type=int, default=6)
    p.add_argument("--J", type=float, default=0.5, help="coupling, MHz")
    p.add_argument("--delta", type=float, default=1.0, help="ZZ anisotropy (1 = isotropic)")
    p.add_argument("--gamma", type=float, default=0.0, help="dephasing rate per spin, MHz")
    # transmon knobs
    p.add_argument("--ej-ec", type=float, default=50.0, help="E_J/E_C ratio (1 = Cooper pair box, 50 = transmon)")
    p.add_argument("--ec", type=float, default=250.0, help="charging energy E_C, MHz")
    p.add_argument("--ng", type=float, default=0.1, help="stray offset charge n_g")
    p.add_argument("--drive", type=float, default=50.0, help="Rabi drive strength, MHz")
    p.add_argument("--t1", type=float, default=30.0, help="T1 relaxation, microseconds (0 = off)")
    p.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "output"))
    a = p.parse_args()

    if a.model == "transmon":
        if a.backend != "cpu":
            p.error("the transmon model is CPU-only (a handful of levels; a GPU adds nothing)")
        a.levels = 4 if a.levels == 15 else min(a.levels, 8)  # 15 is the cavity default
        if a.t_max == 3.0:
            a.t_max = 0.1  # transmon dynamics are nanoseconds
    H, dims, c_ops, obs, psi0, times = MODELS[a.model](a)
    size = int(np.prod(list(dims.values())))
    print(f"model={a.model} backend={a.backend} Hilbert size={size} "
          f"(density matrix {size}x{size}), noise channels={len(c_ops)}")

    t0 = time.perf_counter()
    if a.backend == "both":
        res = run_cpu(H, dims, c_ops, obs, psi0, times)
        t_cpu = time.perf_counter() - t0
        t1 = time.perf_counter()
        res_gpu = run_gpu(H, dims, c_ops, obs, psi0, times)
        print(f"cpu {t_cpu:.2f} s | gpu {time.perf_counter() - t1:.2f} s")
        for k in res:
            print(f"  max |cpu - gpu| for {k:28s} = {np.max(np.abs(res[k] - res_gpu[k])):.2e}")
    else:
        res = (run_gpu if a.backend == "gpu" else run_cpu)(H, dims, c_ops, obs, psi0, times)
    dt = time.perf_counter() - t0
    print(f"solved in {dt:.2f} s")

    os.makedirs(a.out, exist_ok=True)
    tag = f"{a.model}_{a.backend}" + (f"_{a.spins}spins" if a.model == "spinchain" else "")
    with open(os.path.join(a.out, tag + ".csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_us", *res])
        for i, t in enumerate(times):
            w.writerow([f"{t:.5f}", *[f"{res[k][i]:.6f}" for k in res]])

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(len(res), 1, figsize=(8, 2.2 * len(res)), sharex=True)
    for ax, (k, v) in zip(np.atleast_1d(axes), res.items()):
        ax.plot(times, v, lw=1.8)
        ax.set_ylabel(k, fontsize=8)
        ax.grid(alpha=0.3)
    np.atleast_1d(axes)[-1].set_xlabel("time (µs)")
    fig.suptitle(f"{a.model} | {a.backend} | {size}-dim | {dt:.2f}s")
    fig.tight_layout()
    png = os.path.join(a.out, tag + ".png")
    fig.savefig(png, dpi=130)
    print("saved", png)
    for k, v in res.items():
        print(f"  {k:28s} start={v[0]: .3f}  end={v[-1]: .3f}")


if __name__ == "__main__":
    main()
