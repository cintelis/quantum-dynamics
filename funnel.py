"""
Energy funnelling in a quasi-2D (layered) perovskite solar absorber.

A quasi-2D film is a stack of quantum wells of different thickness n (n = 1 is one
lead-halide layer between organic spacers; larger n is closer to bulk 3D). Thinner wells
have higher exciton energy, so light absorbed in an n = 1 well should cascade
downhill n = 1 -> 2 -> 3 ... -> 3D, where charges are extracted. Losses (non-radiative
recombination) compete at every step.

Model (single excitation, open quantum system, Lindblad):
  sites       n = 1 .. n_max and a 3D site; energies from typical exciton peaks
  coherent    coupling J between neighbouring wells (set by spacer length)
  dephasing   gamma on each site (vibrations of the organic spacer)
  relaxation  weak phonon-assisted hopping obeying detailed balance at 300 K
  extraction  3D site -> "collected" at rate k_ex
  loss        every site -> "lost" at rate k_nr
Efficiency = population in "collected" at the end.

Dephasing-assisted transport: with gamma ~ 0 the energy steps (100-300 meV) detune
neighbouring wells and coherent transfer stalls; with gamma huge the quantum Zeno effect
freezes it; in between there is an optimum (Plenio & Huelga 2008; Rebentrost et al. 2009).

Units: energies meV, time picoseconds. hbar = 0.6582 meV ps.
"""
import numpy as np
from scipy.linalg import expm

from transmon import Dense

HBAR = 0.6582119569  # meV * ps
KT = 25.85           # meV at 300 K

# Typical exciton energies (meV) of n-layer lead-halide quantum wells and bulk 3D.
# Iodide: n=1 ~516 nm, n=2 ~570, n=3 ~610, n=4 ~640, n=5 ~660, 3D ~760-800 nm (literature ranges).
LEVELS_MEV = {
    "I":  [2400, 2170, 2030, 1930, 1880, 1550],
    "Br": [3050, 2800, 2650, 2560, 2500, 2300],
}


def spacer_to_params(length_A, rot_bonds, aromatic_rings, dj):
    """Illustrative mapping from spacer descriptors to model parameters.
    Longer spacers -> wells further apart -> weaker coupling (dipole ~ 1/d^3).
    Floppier spacers (rotatable bonds) -> stronger dephasing; aromatic rings stiffen."""
    d = (length_A if dj else 2 * length_A) * 0.8 + 2.0          # well-to-well distance, Angstrom
    J = 40.0 * (6.0 / d) ** 3                                   # meV
    gamma = max(10.0, 30.0 + 15.0 * rot_bonds - 10.0 * aromatic_rings)  # meV
    return dict(d=round(d, 2), J=round(J, 2), gamma=round(gamma, 1))


def _energies(a):
    E = LEVELS_MEV[a.halide][: int(a.n_max)] + [LEVELS_MEV[a.halide][-1]]
    return np.array(E, dtype=float)


def _operators(a, gamma=None):
    """Return H (rad/ps), list of collapse matrices, site count, dimension."""
    E = _energies(a)
    S = len(E)                     # wells + 3D
    D = S + 2                      # + collected + lost
    col, lost = S, S + 1
    w = (E - E.min()) / HBAR       # rad/ps relative to the 3D level
    H = np.zeros((D, D), dtype=complex)
    for i in range(S):
        H[i, i] = w[i]
    Jw = a.J / HBAR
    for i in range(S - 1):
        H[i, i + 1] = H[i + 1, i] = Jw
    g = (a.gamma if gamma is None else gamma) / HBAR
    c = []
    for i in range(S):                       # pure dephasing on each site: coherence decays at g
        P = np.zeros((D, D)); P[i, i] = 1
        c.append(np.sqrt(2 * g) * P)
    for i in range(S - 1):                   # thermal hopping with detailed balance
        dE = E[i] - E[i + 1]                 # > 0: i is higher
        down = np.zeros((D, D)); down[i + 1, i] = 1
        up = np.zeros((D, D)); up[i, i + 1] = 1
        c.append(np.sqrt(a.k_relax) * down)
        c.append(np.sqrt(a.k_relax * np.exp(-dE / KT)) * up)
    for i in range(S):                       # losses
        L = np.zeros((D, D)); L[lost, i] = 1
        c.append(np.sqrt(a.k_nr) * L)
    X = np.zeros((D, D)); X[col, S - 1] = 1  # extraction from 3D
    c.append(np.sqrt(a.k_ex) * X)
    return H, c, S, D


# ---------------------------------------------------------------- disordered film (many patches)
# A real quasi-2D film is a patchwork: grains of different thickness n scattered through the film,
# each with its exciton energy shifted a little by strain and local composition (disorder sigma).
# Patches sit at random positions in a cross-section (x along the film, z = depth from the substrate).
# Thin-n patches gather near the bottom and 3D near the top (as reported for most quasi-2D films).
# Coupling falls off as (d0/r)^3 between nearby patches; phonon hopping as (d0/r)^6.

def _patches(a):
    """Random but reproducible film: returns (n_index per patch [0..n_max, n_max = 3D], energies meV, positions)."""
    rng = np.random.default_rng(int(a.seed))
    N = int(a.patches)
    pos = rng.random((N, 2))                                   # (x, z), z = 0 substrate, 1 top
    classes = int(a.n_max) + 1                                 # n = 1..n_max and 3D
    grade = 0.7 * pos[:, 1] + 0.3 * rng.random(N)              # depth sets thickness, with scatter
    cls = np.minimum((np.argsort(np.argsort(grade)) * classes) // N, classes - 1)  # equal shares per class
    levels = LEVELS_MEV[a.halide]
    base = np.array([levels[k] if k < classes - 1 else levels[-1] for k in cls], dtype=float)
    E = base + rng.normal(0.0, float(a.sigma), N)
    return cls, E, pos


def _disorder_operators(a, gamma=None, J=None):
    cls, E, pos = _patches(a)
    N = len(E)
    D = N + 2
    col, lost = N, N + 1
    d0 = 1.0 / np.sqrt(N)                                      # typical neighbour spacing
    r = np.linalg.norm(pos[:, None, :] - pos[None, :, :], axis=-1)
    near = (r > 0) & (r < 2.5 * d0)
    H = np.zeros((D, D), dtype=complex)
    H[np.arange(N), np.arange(N)] = (E - E.min()) / HBAR
    Jw = (a.J if J is None else J) / HBAR
    with np.errstate(divide="ignore"):
        geo = np.where(near, (d0 / np.maximum(r, 0.35 * d0)) ** 3, 0.0)   # cap so two close grains don't blow up
    H[:N, :N] += Jw * geo
    g = (a.gamma if gamma is None else gamma) / HBAR
    c = []
    for i in range(N):
        P = np.zeros((D, D)); P[i, i] = 1
        c.append(np.sqrt(2 * g) * P)
    iu, ju = np.where(np.triu(near))
    for i, j in zip(iu, ju):
        hi, lo_ = (i, j) if E[i] >= E[j] else (j, i)
        k = a.k_relax * geo[i, j] ** 2
        down = np.zeros((D, D)); down[lo_, hi] = 1
        up = np.zeros((D, D)); up[hi, lo_] = 1
        c.append(np.sqrt(k) * down)
        c.append(np.sqrt(k * np.exp(-abs(E[i] - E[j]) / KT)) * up)
    for i in range(N):
        L = np.zeros((D, D)); L[lost, i] = 1
        c.append(np.sqrt(a.k_nr) * L)
    for i in np.where(cls == int(a.n_max))[0]:                 # every 3D patch can hand charges out
        X = np.zeros((D, D)); X[col, i] = 1
        c.append(np.sqrt(a.k_ex) * X)
    return H, c, N, D, cls, E


def _rho0_disorder(cls, N, D):
    """Light lands in the thinnest layers: an even mixture over all n = 1 patches."""
    start = np.where(cls == 0)[0]
    rho = np.zeros((D, D), dtype=complex)
    rho[start, start] = 1.0 / len(start)
    return rho


def _eventual_yield(H, c, S, rho0_S):
    """Fraction collected as t -> infinity, without time-stepping.

    Restrict the master equation to the S emitting states (the sinks only drain them) and solve
    L(X) = -rho0 for X = integral_0^inf rho dt; then collected = sum_i k_ex,i X_ii.
    Every collapse operator here is one entry |f><i|, so
        L(X) = -i(Heff X - X Heff^+) + diag(W diag(X)),   W[f, i] = rate of jumps i -> f.
    The first part is undone exactly by diagonalising Heff (S x S); the jump part only touches the
    S populations, which leaves an S x S linear system. Cost ~S^3 instead of (S^2)^3."""
    Heff = H[:S, :S].astype(complex).copy()
    W = np.zeros((S, S))
    to_col = np.zeros(S)
    for m in c:
        f, i = np.nonzero(m)
        if len(f) != 1:
            raise ValueError("expected single-entry collapse operators")
        f, i = int(f[0]), int(i[0]); k = abs(m[f, i]) ** 2
        Heff[i, i] -= 0.5j * k
        if f < S:
            W[f, i] += k
        elif f == S:                    # into "collected"
            to_col[i] += k
    lam, V = np.linalg.eig(Heff)
    if np.linalg.cond(V) > 1e10:        # nearly defective: fall back to the full (slow) Liouvillian
        return _eventual_yield_dense(Heff, W, to_col, S, rho0_S)
    Vi = np.linalg.inv(V)
    Dn = -1j * (lam[:, None] - lam.conj()[None, :])          # A(X) = V (Dn * Y) V^+, X = V Y V^+
    def A_inv(B):
        return V @ ((Vi @ B @ Vi.conj().T) / Dn) @ V.conj().T
    X0 = A_inv(-rho0_S)
    # G[j, f] = diag(A^-1(|f><f|))_j
    Pm = (V[:, :, None] * V.conj()[:, None, :]).reshape(S, S * S)                 # [j, (a,b)]
    Qm = ((Vi[:, None, :] * Vi.conj()[None, :, :]) / Dn[:, :, None]).reshape(S * S, S)  # [(a,b), f]
    G = Pm @ Qm
    p = np.linalg.solve(np.eye(S) + G @ W, np.real_if_close(np.diag(X0)))
    return float(np.real(to_col @ p))


def _eventual_yield_dense(Heff, W, to_col, S, rho0_S):
    I = np.eye(S)
    L = -1j * (np.kron(Heff, I) - np.kron(I, Heff.conj()))
    idx = np.arange(S) * (S + 1)
    L[np.ix_(idx, idx)] += W
    X = np.linalg.solve(L, -rho0_S.ravel()).reshape(S, S)
    return float(np.real(to_col @ np.diag(X)))


def disorder_yield(a, gamma=None, J=None):
    H, c, N, D, cls, E = _disorder_operators(a, gamma, J)
    return _eventual_yield(H, c, N, _rho0_disorder(cls, N, D)[:N, :N])


def ideal_yield(a, gamma=None, J=None):
    b = type("A", (), dict(vars(a)))()
    if J is not None:
        b.J = J
    H, c, S, D = _operators(b, gamma)
    r0 = np.zeros((S, S), dtype=complex); r0[0, 0] = 1
    return _eventual_yield(H, c, S, r0)


def _disordered(a):
    return int(getattr(a, "patches", 0) or 0) >= 2


def model(a):
    if _disordered(a):
        return _disorder_model(a)
    H, c, S, D = _operators(a)
    names = [f"n={k + 1}" for k in range(S - 1)] + ["3D"]
    P = lambda i: Dense(np.diag([1.0 if j == i else 0.0 for j in range(D)]))
    obs = {"Collected (efficiency)": P(S), "Lost (recombination)": P(S + 1),
           "In thin wells (n=1…" + str(S - 1) + ")": Dense(np.diag([1.0] * (S - 1) + [0.0] * 3)),
           "In 3D bulk": P(S - 1)}
    psi0 = np.zeros(D, dtype=complex); psi0[0] = 1.0     # photon absorbed in an n=1 well
    times = np.linspace(0, a.t_max, a.steps)
    return Dense(H), {0: D}, [Dense(m) for m in c], obs, psi0, times


def _disorder_model(a):
    H, c, N, D, cls, E = _disorder_operators(a)
    thin = [1.0 if (i < N and cls[i] < int(a.n_max)) else 0.0 for i in range(D)]
    bulk = [1.0 if (i < N and cls[i] == int(a.n_max)) else 0.0 for i in range(D)]
    P = lambda i: Dense(np.diag([1.0 if j == i else 0.0 for j in range(D)]))
    obs = {"Collected (efficiency)": P(N), "Lost (recombination)": P(N + 1),
           "In thin wells (n=1…" + str(int(a.n_max)) + ")": Dense(np.diag(thin)), "In 3D bulk": Dense(np.diag(bulk))}
    times = np.linspace(0, a.t_max, a.steps)
    return Dense(H), {0: D}, [Dense(m) for m in c], obs, _rho0_disorder(cls, N, D), times


def profile(a):
    if _disordered(a):          # 50 rows would be unreadable: group the patches by thickness
        cls, E, _ = _patches(a)
        N = len(E); D = N + 2; K = int(a.n_max) + 1
        rows = np.zeros((K + 2, D))
        labels = []
        for k in range(K):
            idx = np.where(cls == k)[0]
            rows[k, idx] = 1
            name = "3D" if k == K - 1 else f"n={k + 1}"
            labels.append(f"{name} · {len(idx)} patches ({E[idx].mean() / 1000:.2f} eV)")
        rows[K, N] = 1; rows[K + 1, N + 1] = 1
        return ("Where the energy is (patches grouped by thickness)", labels + ["collected", "lost"], rows, "sequential", None)
    E = _energies(a)
    S = len(E); D = S + 2
    labels = [f"n={k + 1} ({E[k] / 1000:.2f} eV)" for k in range(S - 1)] + [f"3D ({E[-1] / 1000:.2f} eV)", "collected", "lost"]
    return ("Where the energy is", labels, np.eye(D), "sequential", None)


def _efficiency(a, gamma=None, J=None):
    """Collected population at t_max, via the matrix exponential of the Liouvillian."""
    b = type("A", (), dict(vars(a)))()
    if J is not None:
        b.J = J
    H, c, S, D = _operators(b, gamma)
    I = np.eye(D)
    Heff = H - 0.5j * sum(m.conj().T @ m for m in c)
    L = -1j * (np.kron(Heff, I) - np.kron(I, Heff.conj()))
    for m in c:
        L += np.kron(m, m.conj())
    rho0 = np.zeros((D, D), dtype=complex); rho0[0, 0] = 1
    # Small matrix: diagonalise once, exponentiate the eigenvalues (much faster than expm at large norm).
    lam, V = np.linalg.eig(L)
    if np.linalg.cond(V) < 1e10:
        coef = np.linalg.solve(V, rho0.ravel())
        rho = (V @ (np.exp(lam * a.t_max) * coef)).reshape(D, D)
    else:  # nearly defective: fall back to the exact matrix exponential
        rho = (expm(L * a.t_max) @ rho0.ravel()).reshape(D, D)
    return float(np.real(rho[S, S])), float(np.real(rho[S + 1, S + 1]))


def _disorder_charts(a):
    gs = np.geomspace(1, 2000, 25)
    Js = np.geomspace(0.5, 100, 21)
    sig = np.linspace(0, 150, 16)
    seeds = [int(a.seed) + k for k in range(5)]
    def avg(**kw):
        vals = []
        for sd in seeds:
            b = type("A", (), dict(vars(a)))(); b.seed = sd
            for k, v in kw.items():
                setattr(b, k, v)
            vals.append(disorder_yield(b, gamma=kw.get("gamma"), J=kw.get("J")))
        return float(np.mean(vals))
    eff_g = [disorder_yield(a, gamma=g) for g in gs]
    ide_g = [ideal_yield(a, gamma=g) for g in gs]
    eff_J = [disorder_yield(a, J=j) for j in Js]
    ide_J = [ideal_yield(a, J=j) for j in Js]
    eff_s = [avg(sigma=s) for s in sig]
    return [
        dict(title="Eventual efficiency vs dephasing γ: disordered film vs ideal staircase",
             note=f"{int(a.patches)} patches, σ = {a.sigma:g} meV. Eventual = everything collected or lost (t → ∞)",
             xlabel="dephasing γ (meV)", ylabel="collected", log=False, logx=True, marker=round(a.gamma, 1),
             x=gs.tolist(), series=[dict(name="disordered film", y=eff_g), dict(name="ideal staircase", y=ide_g)]),
        dict(title="Eventual efficiency vs coupling J",
             note="Disorder opens side paths between grains; the ideal staircase has one route down",
             xlabel="coupling J (meV)", ylabel="collected", log=False, logx=True, marker=round(a.J, 2),
             x=Js.tolist(), series=[dict(name="disordered film", y=eff_J), dict(name="ideal staircase", y=ide_J)]),
        dict(title="Eventual efficiency vs energy disorder σ (average of 5 random films)",
             note="Some disorder fills in the gaps between steps; a lot of it creates traps",
             xlabel="disorder σ (meV)", ylabel="collected", log=False, logx=False, marker=round(a.sigma, 1),
             x=sig.tolist(), series=[dict(name="disordered film", y=eff_s)]),
    ]


def static_charts(a):
    if _disordered(a):
        return _disorder_charts(a)
    gs = np.geomspace(1, 2000, 33)
    eff = [_efficiency(a, gamma=g)[0] for g in gs]
    Js = np.geomspace(0.5, 100, 25)
    effJ = [_efficiency(a, J=j)[0] for j in Js]
    best = gs[int(np.argmax(eff))]
    return [
        dict(title="Efficiency vs dephasing γ (spacer vibrations)",
             note=f"Noise-assisted transport: best near γ ≈ {best:.0f} meV for these energy steps",
             xlabel="dephasing γ (meV)", ylabel="collected", log=False, logx=True, marker=round(a.gamma, 1),
             x=gs.tolist(), series=[dict(name="efficiency", y=eff)]),
        dict(title="Efficiency vs inter-well coupling J (shorter spacer → larger J)",
             note="Stronger coupling moves energy downhill before it is lost",
             xlabel="coupling J (meV)", ylabel="collected", log=False, logx=True, marker=round(a.J, 2),
             x=Js.tolist(), series=[dict(name="efficiency", y=effJ)]),
    ]


def _disorder_tiles(a):
    H, c, N, D, cls, E = _disorder_operators(a)
    eff = disorder_yield(a)
    ide = ideal_yield(a)
    K = int(a.n_max) + 1
    counts = [int(np.sum(cls == k)) for k in range(K)]
    n1 = E[cls == 0]
    return [
        dict(k="Eventual efficiency", v=f"{100 * eff:.1f}%", h="all energy collected or lost (t → ∞)"),
        dict(k="Ideal staircase, same J and γ", v=f"{100 * ide:.1f}%",
             h=("disorder helps" if eff > ide else "disorder hurts") + f" by {abs(100 * (eff - ide)):.1f} points"),
        dict(k="Film", v=f"{N} patches · σ {a.sigma:g} meV",
             h="per thickness: " + ", ".join(f"{'3D' if k == K - 1 else 'n=' + str(k + 1)} {counts[k]}" for k in range(K))),
        dict(k="n=1 energy spread", v=f"{n1.min() / 1000:.2f}–{n1.max() / 1000:.2f} eV", h=f"random film #{int(a.seed)}"),
        dict(k="Spacer", v=_short(getattr(a, "spacer_name", "")) or "custom",
             h=getattr(a, "spacer_name", "") or "set J and γ directly"),
    ]


def derived_tiles(a):
    if _disordered(a):
        return _disorder_tiles(a)
    E = _energies(a)
    eff, lost = _efficiency(a)
    steps = np.diff(E[::-1])[::-1] if len(E) > 1 else []
    k_est = [2 * (a.J / HBAR) ** 2 * (a.gamma / HBAR) / ((a.gamma / HBAR) ** 2 + (s / HBAR) ** 2) for s in -np.diff(E)]
    slowest = min(k_est) if k_est else float("nan")
    return [
        dict(k="Efficiency at end", v=f"{100 * eff:.1f}%", h=f"lost {100 * lost:.1f}% · rest still in transit"),
        dict(k="Energy staircase", v=f"{E[0] / 1000:.2f} → {E[-1] / 1000:.2f} eV",
             h="n=1 … 3D: " + " → ".join(f"{e / 1000:.2f}" for e in E)),
        dict(k="Coupling J · dephasing γ", v=f"{a.J:g} · {a.gamma:g} meV", h="from spacer length and rigidity"),
        dict(k="Slowest hop (estimate)", v=f"{1 / slowest:.2g} ps" if slowest > 0 else "—",
             h="Förster-like rate 2J²γ/(γ²+Δ²) for the biggest step"),
        dict(k="Spacer", v=_short(getattr(a, "spacer_name", "")) or "custom",
             h=getattr(a, "spacer_name", "") or "set J and γ directly"),
    ]


def _short(name):
    """'Butane-1,4-diammonium ((BDA)FA4Pb5I16)' -> 'Butane-1,4-diammonium', capped for a tile."""
    n = name.split(" (")[0].strip()
    return n if len(n) <= 22 else n[:21] + "…"
