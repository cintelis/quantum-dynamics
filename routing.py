"""
Delivery routing with QAOA on CUDA-Q: split delivery stops between two vans.

The problem
  N stops on a 10 x 10 km map, van A starts at a depot on the west side, van B on the east side. Each stop goes to
  one van. A plan costs:
    - the distance from each stop to its van's depot (stay close to home),
    - half the distance between every two stops that share a van (keep each van's stops together),
    - a penalty for uneven loads: LOAD x (stops on A - stops on B)^2.

As qubits
  One qubit per stop: |0> = van A, |1> = van B. With z = +1 / -1 for A / B the cost is a sum of single-qubit (h_i z_i)
  and pair (J_ij z_i z_j) terms, which is an Ising Hamiltonian. QAOA prepares an even mix of every plan, then
  alternates "cost" layers (phases from h and J) with "mixer" layers (X rotations); a classical optimiser tunes the
  angles to lower the average cost, and sampling the final state gives the plans to keep.

The route each van drives through its stops is then ordered classically (exact for this size). Every plan is
also checked by brute force, so the page can show how close QAOA came. This is a teaching-size problem: at 6-12
stops a laptop checks every plan instantly, and classical solvers win at real sizes today.

    python routing.py --stops 8 --layers 2          # one run, printed
"""
import itertools
import math
import time

import numpy as np

LOAD = 1.2                  # km per (difference in stop counts)^2
PAIR = 0.5                  # weight on the distance between two stops that share a van
DEPOTS = {"A": (0.8, 5.0), "B": (9.2, 5.0)}
LIMITS = {"stops": (6, 12), "layers": (1, 4), "seed": (0, 9999)}


def make_map(stops, seed):
    """Stops spread over the map (no two closer than 0.9 km), from a seed so a map can be shared and rerun."""
    rng = np.random.default_rng(seed)
    pts = []
    while len(pts) < stops:
        p = (round(float(rng.uniform(1.6, 8.4)), 2), round(float(rng.uniform(0.8, 9.2)), 2))
        if all(math.dist(p, q) > 0.9 for q in pts) and all(math.dist(p, d) > 0.9 for d in DEPOTS.values()):
            pts.append(p)
    return pts


def ising(pts):
    """Cost = const + sum h_i z_i + sum J_ij z_i z_j  (z = +1 van A, -1 van B), in km."""
    n = len(pts)
    dA = [math.dist(p, DEPOTS["A"]) for p in pts]
    dB = [math.dist(p, DEPOTS["B"]) for p in pts]
    const = sum(dA[i] + dB[i] for i in range(n)) / 2 + LOAD * n
    h = [(dA[i] - dB[i]) / 2 for i in range(n)]
    J = {}
    for i, j in itertools.combinations(range(n), 2):
        d = PAIR * math.dist(pts[i], pts[j])
        const += d / 2                               # same van: (1 + z_i z_j) / 2 * d
        J[(i, j)] = d / 2 + 2 * LOAD                 # load: LOAD (sum z)^2 = LOAD (n + 2 sum_{i<j} z_i z_j)
    return const, h, J


def cost(bits, const, h, J):
    """bits: string of 0 (A) / 1 (B), qubit 0 first."""
    z = [1 - 2 * int(b) for b in bits]
    return const + sum(hi * zi for hi, zi in zip(h, z)) + sum(w * z[i] * z[j] for (i, j), w in J.items())


def all_costs(n, const, h, J):
    """Every plan's cost, indexed like a CUDA-Q state vector: bit i of the index is qubit i (stop i)."""
    k = np.arange(2 ** n)
    z = 1 - 2 * ((k[:, None] >> np.arange(n)[None, :]) & 1)
    c = const + z @ np.array(h)
    for (i, j), w in J.items():
        c = c + w * z[:, i] * z[:, j]
    return c


def bits_of(k, n):
    """Index -> plan string, stop 0 first (the order CUDA-Q prints samples in)."""
    return format(int(k), f"0{n}b")[::-1]


def index_of(bits):
    return int(bits[::-1], 2)


def best_route(depot, stops):
    """Shortest depot -> stops -> depot loop (Held-Karp; exact, fine for up to ~12 stops)."""
    if not stops:
        return [], 0.0
    pts = [depot] + stops
    m = len(stops)
    D = [[math.dist(a, b) for b in pts] for a in pts]
    best = {(1 << i, i): (D[0][i + 1], [i]) for i in range(m)}
    for size in range(2, m + 1):
        for subset in itertools.combinations(range(m), size):
            mask = sum(1 << i for i in subset)
            for last in subset:
                prev = mask ^ (1 << last)
                best[(mask, last)] = min(((best[(prev, k)][0] + D[k + 1][last + 1], best[(prev, k)][1] + [last])
                                          for k in subset if k != last), key=lambda t: t[0])
    full = (1 << m) - 1
    length, order = min(((best[(full, k)][0] + D[k + 1][0], best[(full, k)][1]) for k in range(m)), key=lambda t: t[0])
    return order, length


def plan_routes(pts, bits):
    """Van routes for a plan: {"A": {"stops": [stop indices in driving order], "km": ...}, "B": {...}}."""
    out = {}
    for van, b in (("A", "0"), ("B", "1")):
        idx = [i for i, x in enumerate(bits) if x == b]
        order, km = best_route(DEPOTS[van], [pts[i] for i in idx])
        out[van] = {"stops": [idx[k] for k in order], "km": round(km, 2)}
    return out


def problem(stops, seed):
    """Everything the page needs before any quantum run: the map, every plan's cost and the exact best plan."""
    pts = make_map(stops, seed)
    const, h, J = ising(pts)
    costs = all_costs(stops, const, h, J)
    k = int(np.argmin(costs))
    best = bits_of(k, stops)
    return {
        "stops": stops, "seed": seed, "points": pts, "depots": DEPOTS, "load_penalty": LOAD, "pair_weight": PAIR,
        "plans": 2 ** stops, "terms": {"single": stops, "pairs": len(J)},
        "best": {"bits": best, "cost": round(float(costs[k]), 3), "routes": plan_routes(pts, best)},
        "worst_cost": round(float(costs.max()), 3), "mean_cost": round(float(costs.mean()), 3),
        "_ising": (const, h, J), "_costs": costs,
    }


def public(p):
    return {k: v for k, v in p.items() if not k.startswith("_")}


# ---------------------------------------------------------------- QAOA
# The circuit: start in an even mix of every plan, then per layer l a cost step exp(-i gamma_l C) (rz on each qubit,
# cx-rz-cx on each pair) and a mixer step exp(-i beta_l X) on every qubit. C is the plan cost scaled to unit spread.
#
# Tuning the angles takes hundreds of evaluations. CUDA-Q 0.16's Python layer spends ~0.1-4 s preparing each call
# on a CPU, so the angles are tuned on an exact NumPy model of the same circuit (diagonal phases plus one-qubit
# rotations, so the model is a few lines), and the tuned circuit is then run once on CUDA-Q for the samples.
# The result reports the model's average plan cost next to CUDA-Q's sampled one, so any mismatch would show.

def _np_state(n, layers, theta, diag):
    psi = np.full(2 ** n, 2 ** (-n / 2), dtype=complex)
    for l in range(layers):
        psi = psi * np.exp(-1j * theta[l] * diag)
        c, s = np.cos(theta[layers + l]), -1j * np.sin(theta[layers + l])
        t = psi.reshape((2,) * n)
        for ax in range(n):
            t0, t1 = np.take(t, 0, axis=ax), np.take(t, 1, axis=ax)
            t = np.stack([c * t0 + s * t1, s * t0 + c * t1], axis=ax)
        psi = t.reshape(-1)
    return psi


def _kernel():
    import cudaq

    @cudaq.kernel
    def qaoa(n: int, layers: int, theta: list[float], hs: list[float], ii: list[int], jj: list[int], js: list[float]):
        q = cudaq.qvector(n)
        h(q)
        for l in range(layers):
            for k in range(n):
                rz(2.0 * theta[l] * hs[k], q[k])
            for e in range(len(js)):
                x.ctrl(q[ii[e]], q[jj[e]])
                rz(2.0 * theta[l] * js[e], q[jj[e]])
                x.ctrl(q[ii[e]], q[jj[e]])
            for k in range(n):
                rx(2.0 * theta[layers + l], q[k])

    return qaoa


_KERNEL = None


def tune(n, layers, diag, costs, on_step=None, maxiter=150):
    """Layer by layer: a grid search for one layer, then each extra layer starts from the last one's angles
    stretched to the new depth, polished with COBYLA. Streams every evaluation as {i, layer, expected, best}."""
    from scipy.optimize import minimize
    probs = lambda L, th: np.abs(_np_state(n, L, th, diag)) ** 2
    history, steps, t0 = [], [], time.perf_counter()

    def f_for(L):
        def f(th):
            e = float(probs(L, th) @ costs)
            history.append(e)
            if on_step:
                on_step({"i": len(history), "layer": L, "expected": round(e, 4), "best": round(min(history), 4),
                         "elapsed": round(time.perf_counter() - t0, 3)})
            return e
        return f

    G, B = np.linspace(0.02, 1.2, 30), np.linspace(0.02, 1.55, 24)
    e0, g0, b0 = min((float(probs(1, [g, b]) @ costs), g, b) for g in G for b in B)
    theta = [g0, b0]
    for L in range(1, layers + 1):
        if L > 1:
            xs, xp = np.linspace(0, 1, L), np.linspace(0, 1, L - 1)
            theta = list(np.interp(xs, xp, theta[:L - 1])) + list(np.interp(xs, xp, theta[L - 1:]))
        before = len(history)
        r = minimize(f_for(L), theta, method="COBYLA", options={"maxiter": maxiter, "rhobeg": 0.1})
        theta = list(map(float, r.x))
        steps.append(len(history) - before)
    return theta, history, {"grid_points": len(G) * len(B), "grid_best": round(e0, 4), "layer_steps": steps}


def run(stops, layers, seed, on_step=None, shots=2000, sample=True, before_sample=None):
    """Tune the angles, run the tuned circuit on CUDA-Q, and compare its samples with the exact best plan."""
    global _KERNEL
    p = problem(stops, seed)
    const, h, J = p["_ising"]
    costs = p["_costs"]
    n = stops
    sd = float(costs.std())
    diag = (costs - float(costs.mean())) / sd      # the circuit's cost operator: plan cost scaled to unit spread
    t0 = time.perf_counter()
    theta, history, grid = tune(n, layers, diag, costs, on_step)
    t_tune = time.perf_counter() - t0
    model_p = np.abs(_np_state(n, layers, theta, diag)) ** 2
    order = np.argsort(costs, kind="stable")
    rank = np.empty(len(costs), dtype=int)
    rank[order] = np.arange(1, len(costs) + 1)
    best_mask = np.abs(costs - costs.min()) < 1e-9

    out = public(p)
    out.update({
        "layers": layers, "qubits": n, "theta": [round(t, 4) for t in theta], "evaluations": len(history),
        "history": [round(v, 4) for v in history], "grid": grid, "layer_steps": grid.pop("layer_steps"), "tune_seconds": round(t_tune, 3),
        "expected_model": round(float(model_p @ costs), 4), "p_best_model": round(float(model_p[best_mask].sum()), 5),
        "p_random": round(float(best_mask.mean()), 6),
        "gates": n + layers * (2 * n + 3 * len(J)),
    })
    if not sample:
        return out

    if before_sample:
        before_sample()
    import cudaq
    if _KERNEL is None:
        _KERNEL = _kernel()
    hs = [v / sd for v in h]                       # same scaling as diag (the constant only adds a global phase)
    ii = [i for i, _ in J]
    jj = [j for _, j in J]
    js = [J[e] / sd for e in J]
    t1 = time.perf_counter()
    counts = cudaq.sample(_KERNEL, n, layers, theta, hs, ii, jj, js, shots_count=shots)
    t_q = time.perf_counter() - t1
    samples = sorted(((b, c) for b, c in counts.items()), key=lambda t: (-t[1], costs[index_of(t[0])]))
    got = {index_of(b): c for b, c in samples}
    mean_q = sum(costs[k] * c for k, c in got.items()) / shots
    found_k = min(got, key=lambda k: costs[k])
    row = lambda b, c: {"bits": b, "count": c, "p": round(c / shots, 4), "cost": round(float(costs[index_of(b)]), 3),
                        "rank": int(rank[index_of(b)])}
    top = [row(b, c) for b, c in sorted(samples, key=lambda t: costs[index_of(t[0])])[:10]]   # cheapest plans sampled
    common = row(*samples[0])                                                                  # the most frequent one
    found = bits_of(found_k, n)
    out.update({
        "shots": shots, "distinct": len(got), "top": top, "most_common": common, "target": cudaq.get_target().name,
        "quantum_seconds": round(t_q, 3), "expected_samples": round(float(mean_q), 4),
        "p_best": round(sum(c for k, c in got.items() if best_mask[k]) / shots, 5),
        "found": {"bits": found, "cost": round(float(costs[found_k]), 3), "rank": int(rank[found_k]),
                  "count": got[found_k], "routes": plan_routes(p["points"], found)},
    })
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--stops", type=int, default=8)
    ap.add_argument("--layers", type=int, default=2)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--save", action="store_true", help="write the run to data/routing_example.json for the page")
    a = ap.parse_args()
    r = run(a.stops, a.layers, a.seed)
    if a.save:
        import json, os
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "routing_example.json"), "w") as f:
            json.dump(dict(r, example=True), f, separators=(",", ":"))
    print(f"{r['qubits']} qubits, {r['layers']} layers, {r['gates']} gates: tuned in {r['tune_seconds']} s "
          f"({r['evaluations']} evaluations), sampled on {r['target']} in {r['quantum_seconds']} s")
    print(f"exact best {r['best']['bits']} {r['best']['cost']} km | best sample {r['found']['bits']} {r['found']['cost']} km "
          f"(rank {r['found']['rank']} of {r['plans']})")
    print(f"average plan: random {r['mean_cost']} km, QAOA model {r['expected_model']}, CUDA-Q samples {r['expected_samples']}")
    print(f"P(best): random {r['p_random']:.4f}, model {r['p_best_model']:.4f}, CUDA-Q {r['p_best']:.4f}; "
          f"{r['distinct']} distinct plans in {r['shots']} samples")
