"""
Transmon qubit, after Koch et al., "Charge-insensitive qubit design derived from the
Cooper pair box", Phys. Rev. A 76, 042319 (2007), arXiv:cond-mat/0703002.

The circuit: a Josephson junction (energy E_J) shunted by a capacitor (charging energy E_C).
    H = 4 E_C (n - n_g)^2 - E_J cos(phi)
n = Cooper pairs on the island, n_g = offset charge set by stray charges in the chip.
In the charge basis cos(phi) couples n -> n+1, so H is a small tridiagonal matrix we
diagonalise exactly. Units: frequencies in MHz (energy / h), time in microseconds.

E_J/E_C ~ 1   -> Cooper pair box: energy levels swing wildly with n_g (charge noise kills it)
E_J/E_C ~ 50  -> transmon: levels flat in n_g (exponentially), anharmonicity only ~ -E_C
"""
import numpy as np

TWO_PI = 2 * np.pi
NCUT = 25  # charge states -NCUT..NCUT; plenty for E_J/E_C <= 100


def solve(ej, ec, ng, levels=6, ncut=NCUT):
    """Exact eigen-energies (MHz) and charge-operator matrix in the eigenbasis."""
    n = np.arange(-ncut, ncut + 1)
    H = np.diag(4 * ec * (n - ng) ** 2) - 0.5 * ej * (np.eye(len(n), k=1) + np.eye(len(n), k=-1))
    E, V = np.linalg.eigh(H)
    E, V = E[:levels], V[:, :levels]
    n_op = V.T @ np.diag(n - ng) @ V  # charge matrix elements <j|n|k>
    return E, n_op


def derived(ej, ec):
    """The paper's headline numbers for one design."""
    E0, n0 = solve(ej, ec, 0.0, 4)
    Eh, _ = solve(ej, ec, 0.5, 4)
    f01 = E0[1] - E0[0]
    alpha = (E0[2] - E0[1]) - f01
    eps = Eh - E0                       # charge dispersion of each level, eps_m = E_m(1/2) - E_m(0)
    eps01 = abs(eps[1] - eps[0])        # peak-to-peak wobble of the qubit frequency
    return dict(f01=f01, alpha=alpha, eps=eps, eps01=eps01, n01=abs(n0[0, 1]))


def t2_charge_us(eps01, A=1e-4):
    """Dephasing time from 1/f charge noise of amplitude A (in units of e), paper Sec. V:
    T2 ~ hbar / (A pi |eps|). With eps in MHz this is 1 / (A * pi * 2pi * eps) microseconds."""
    return np.inf if eps01 <= 0 else 1.0 / (A * np.pi * TWO_PI * eps01)


# ------------------------------------------------------------------ static charts (paper figures)

def static_charts(ej_ec, ec):
    ej = ej_ec * ec
    charts = []

    # Fig. 2: levels vs offset charge, normalised by E01 at the charge sweet spot n_g = 1/2
    ngs = np.linspace(-2, 2, 161)
    En = np.array([solve(ej, ec, g, 4)[0] for g in ngs])
    Eh, _ = solve(ej, ec, 0.5, 4)
    E01h = Eh[1] - Eh[0]
    base = En[:, 0].min()
    charts.append(dict(
        title=f"Energy levels vs offset charge n_g  ·  E_J/E_C = {ej_ec:g}",
        note="Flat lines = stray charge cannot move the qubit frequency (paper Fig. 2)",
        xlabel="offset charge n_g", ylabel="E_m / E_01", log=False,
        x=ngs.tolist(),
        series=[dict(name=f"E{m}", y=((En[:, m] - base) / E01h).tolist()) for m in range(4)],
    ))

    # Fig. 4 / Eq. 2.18: charge dispersion falls exponentially with E_J/E_C
    ratios = np.unique(np.concatenate([np.geomspace(0.5, 100, 70), [ej_ec]]))
    d0, d1, ar = [], [], []
    for r in ratios:
        d = derived(r * ec, ec)
        d0.append(abs(d["eps"][0]) / d["f01"])
        d1.append(abs(d["eps"][1]) / d["f01"])
        ar.append(d["alpha"] / d["f01"])
    floor = 1e-13  # below this the double-precision eigenvalues are noise
    clip = lambda v: [x if x > floor else None for x in v]
    charts.append(dict(
        title="Charge dispersion |ε_m| / E_01  (log scale)",
        note="Sensitivity to stray charge drops exponentially, ~exp(−√(8 E_J/E_C))",
        xlabel="E_J / E_C", ylabel="|ε_m| / E_01", log=True, marker=ej_ec,
        x=ratios.tolist(),
        series=[dict(name="ground ε0", y=clip(d0)), dict(name="excited ε1", y=clip(d1))],
    ))
    charts.append(dict(
        title="Relative anharmonicity α / E_01",
        note="…while anharmonicity (what makes it a qubit) shrinks only slowly",
        xlabel="E_J / E_C", ylabel="α_r", log=False, marker=ej_ec,
        x=ratios.tolist(),
        series=[dict(name="α_r", y=ar)],
    ))
    return charts


# ------------------------------------------------------------------ dynamics: driving the qubit

class Dense:
    """A fixed matrix that looks like a CUDA-Q operator to sim.stream_cpu (to_matrix(dims))."""
    def __init__(self, m):
        self.m = np.asarray(m, dtype=complex)

    def to_matrix(self, dims=None):
        return self.m


def model(a):
    """Resonant Rabi drive on the 0-1 transition, in the frame rotating at the drive frequency.

    The drive is tuned to the qubit frequency at n_g = 0. A stray offset charge (a.ng)
    shifts the real levels; how much depends on E_J/E_C. Includes all `levels` transmon
    levels, so strong drives leak into |2> (anharmonicity too small to stay a 2-level system).
    Noise: T1 relaxation and Markovian charge-noise dephasing (rate from the charge dispersion).
    """
    ec, L = a.ec, int(a.levels)
    ej = a.ej_ec * ec
    E_cal, _ = solve(ej, ec, 0.0, L)
    E, n_op = solve(ej, ec, a.ng, L)
    wd = E_cal[1] - E_cal[0]                       # drive frequency (MHz), calibrated at n_g = 0
    n01 = abs(n_op[0, 1])

    H = np.zeros((L, L), dtype=complex)
    for k in range(L):
        H[k, k] = TWO_PI * (E[k] - E[0] - k * wd)  # detuning of each level in the rotating frame
    for k in range(L - 1):                         # drive couples k <-> k+1 via the charge operator
        g = TWO_PI * a.drive / 2 * abs(n_op[k, k + 1]) / n01
        H[k, k + 1] = H[k + 1, k] = g

    c_ops = []
    if a.t1 > 0:
        lower = np.zeros((L, L))
        for k in range(L - 1):
            lower[k, k + 1] = abs(n_op[k, k + 1]) / n01
        c_ops.append(Dense(np.sqrt(1.0 / a.t1) * lower))
    d = derived(ej, ec)
    t2 = t2_charge_us(d["eps01"])
    if np.isfinite(t2):
        eps_all = solve(ej, ec, 0.5, L)[0] - solve(ej, ec, 0.0, L)[0]
        Dm = np.diag((eps_all - eps_all[0]) / max(abs(eps_all[1] - eps_all[0]), 1e-30))
        c_ops.append(Dense(np.sqrt(2.0 / t2) * Dm))

    P = lambda k: Dense(np.diag([1.0 if j == k else 0.0 for j in range(L)]))
    leak = Dense(np.diag([0.0, 0.0] + [1.0] * (L - 2)))
    sy = np.zeros((L, L), dtype=complex); sy[0, 1], sy[1, 0] = -1j, 1j
    obs = {
        "P(0) ground": P(0),
        "P(1) excited": P(1),
        "P(≥2) leakage out of the qubit": leak,
        "qubit ⟨Y⟩ (0–1 coherence)": Dense(sy),
    }
    psi0 = np.zeros(L, dtype=complex); psi0[0] = 1.0
    times = np.linspace(0, a.t_max, a.steps)
    return Dense(H), {0: L}, c_ops, obs, psi0, times


def profile(a):
    L = int(a.levels)
    return ("Level populations P(k)", [f"|{k}⟩" for k in range(L)], np.eye(L), "sequential", None)


def derived_tiles(a):
    ej, ec = a.ej_ec * a.ec, a.ec
    d = derived(ej, ec)
    E_cal, _ = solve(ej, ec, 0.0, 2)
    E_ng, _ = solve(ej, ec, a.ng, 2)
    shift = (E_ng[1] - E_ng[0]) - (E_cal[1] - E_cal[0])
    t2 = t2_charge_us(d["eps01"])
    def fmt_t(t):
        if not np.isfinite(t): return "∞"
        if t >= 1e6: return f"{t / 1e6:.3g} s"
        if t >= 1e3: return f"{t / 1e3:.3g} ms"
        if t >= 1: return f"{t:.3g} µs"
        return f"{t * 1e3:.3g} ns"
    return [
        dict(k="Qubit frequency f01", v=f"{d['f01'] / 1000:.3f} GHz", h=f"E_J = {ej / 1000:.2f} GHz · E_C = {ec:g} MHz"),
        dict(k="Anharmonicity α", v=f"{d['alpha']:.0f} MHz", h=f"{100 * d['alpha'] / d['f01']:.1f}% of f01 · ≈ −E_C for a transmon"),
        dict(k="Charge dispersion", v=_mhz(d["eps01"]), h="how far stray charge can push f01"),
        dict(k="Shift from n_g = " + f"{a.ng:g}", v=_mhz(shift), h="drive is now off-resonant by this much"),
        dict(k="T2 limit from charge noise", v=fmt_t(t2), h="1/f noise, A = 10⁻⁴ e (paper Sec. V)"),
    ]


def _mhz(x):
    x = abs(x)
    if x >= 1: return f"{x:.3g} MHz"
    if x >= 1e-3: return f"{x * 1e3:.3g} kHz"
    if x >= 1e-6: return f"{x * 1e6:.3g} Hz"
    return f"{x * 1e6:.1e} Hz"
