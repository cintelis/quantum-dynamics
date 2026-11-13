"""
Step 1 (free, local): check the spin-chain circuit before using any IBM quantum time.

For 6 and 9 spins (dashboard J = 0.5 MHz, delta = 1, gamma = 0, 0..1 us) compare:
  exact       the dashboard's own solver (sim.run_cpu)
  circuit     the Trotter circuit on a perfect simulator (Aer, exact expectation values): only the time-slicing error
  ibm noise   the same circuit compiled for IBM's 156-qubit ibm_fez and run on Aer with that chip's recorded noise
              (qiskit-ibm-runtime offline backend: calibration snapshot, not live). No error mitigation: this is the raw
              noise floor the real run would start from.
Also reports what the circuits cost on the chip (two-qubit gates, depth) and how the time-slice size dt trades accuracy
against depth.

Output: data/ibm/step1.json, output/ibm_step1.png
"""
import json
import os
import sys
import time
import types

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from spinchain_qiskit import trotter_circuit, observables, steps_for  # noqa: E402

J, DELTA, T_MAX = 0.5, 1.0, 1.0   # 0..1 us: the Neel order collapses and rebounds once
TIMES = np.round(np.linspace(0, T_MAX, 21), 4)
DT_SWEEP = (0.0125, 0.02, 0.025, 1 / 30, 0.05, 0.1)   # us per Trotter step
ERR_TARGET = 0.03   # largest dt whose perfect-qubit circuit stays within this of exact is used for the noisy run
DT = None
SHOTS = 4096


def exact(N):
    import sim
    a = types.SimpleNamespace(spins=N, J=J, delta=DELTA, gamma=0.0, t_max=T_MAX, steps=len(TIMES))
    H, dims, c_ops, obs, psi0, times = sim.model_spinchain(a)
    res = sim.run_cpu(H, dims, c_ops, obs, psi0, times)
    return {k: np.asarray(v).tolist() for k, v in res.items()}


def ideal(N, dt):
    from qiskit_aer.primitives import EstimatorV2
    est = EstimatorV2()                              # default precision 0 -> exact expectation values
    obs = observables(N)
    circs = [trotter_circuit(N, J, DELTA, t, steps_for(t, dt)) for t in TIMES]
    job = est.run([(c, list(obs.values())) for c in circs])
    vals = np.array([r.data.evs for r in job.result()])          # [time, observable]
    return {k: vals[:, i].tolist() for i, k in enumerate(obs)}


def ibm_noise(N, dt):
    from qiskit.transpiler import generate_preset_pass_manager
    from qiskit_ibm_runtime import EstimatorV2
    from qiskit_ibm_runtime.fake_provider import FakeFez
    backend = FakeFez()
    pm = generate_preset_pass_manager(backend=backend, optimization_level=3, seed_transpiler=7)
    obs = observables(N)
    circs = [trotter_circuit(N, J, DELTA, t, steps_for(t, dt)) for t in TIMES]
    isa = pm.run(circs)
    stats = []
    for t, c in zip(TIMES, isa):
        ops = c.count_ops()
        stats.append(dict(t=float(t), steps=steps_for(t, dt), two_qubit=int(ops.get("cz", 0) + ops.get("ecr", 0)),
                          depth=c.depth()))
    est = EstimatorV2(mode=backend)                   # local testing mode: Aer + this chip's noise model
    est.options.default_shots = SHOTS
    pubs = [(c, [o.apply_layout(c.layout) for o in obs.values()]) for c in isa]
    res = est.run(pubs).result()
    vals = np.array([r.data.evs for r in res])
    errs = np.array([r.data.stds for r in res])
    return ({k: vals[:, i].tolist() for i, k in enumerate(obs)},
            {k: errs[:, i].tolist() for i, k in enumerate(obs)}, stats,
            [int(q) for q in isa[-1].layout.final_index_layout()])


def max_err(a, b):
    return float(np.max(np.abs(np.asarray(a) - np.asarray(b))))


def chart(results, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    bg, ink, muted, grid = "#141414", "#e8e8e8", "#9a9a9a", "#2a2a2a"
    col = {"exact": "#6aa800", "circuit": "#3987e5", "ibm": "#d95926"}
    fig, axes = plt.subplots(1, len(results), figsize=(6.2 * len(results), 3.8), facecolor=bg)
    for ax, (N, r) in zip(np.atleast_1d(axes), results.items()):
        ax.set_facecolor(bg)
        k = "staggered magnetisation"
        ax.plot(TIMES, r["exact"][k], color=col["exact"], lw=2, label="exact (dashboard solver)")
        ax.plot(TIMES, r["circuit"][k], "o", ms=6, mfc=col["circuit"], mec=bg, mew=1.5, label=f"circuit, perfect qubits (dt = {DT * 1000:.0f} ns)")
        ax.errorbar(TIMES, r["ibm"][k], yerr=r["ibm_std"][k], fmt="s", ms=5.5, color=col["ibm"], mec=bg, mew=1.5,
                    elinewidth=1, capsize=0, label="circuit, ibm_fez noise (no mitigation)")
        ax.axhline(0, color=grid, lw=1)
        ax.set_title(f"{N} spins · staggered magnetisation", color=ink, fontsize=11, loc="left")
        ax.set_xlabel("time (µs)", color=muted); ax.set_ylim(-0.7, 1.08)
        ax.tick_params(colors=muted); ax.grid(color=grid, lw=0.6)
        for s in ax.spines.values():
            s.set_visible(False)
    leg = np.atleast_1d(axes)[0].legend(loc="upper right", frameon=False, fontsize=8.5)
    for t in leg.get_texts():
        t.set_color(ink)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=bg)


def main():
    global DT
    out = dict(model=dict(J_MHz=J, delta=DELTA, gamma=0.0, t_max_us=T_MAX, dt_us=DT, shots=SHOTS,
                          backend_noise="FakeFez (ibm_fez calibration snapshot, offline)"), sizes={})
    results = {}
    for N in (6, 9):
        t0 = time.time()
        r = dict(exact=exact(N)); t_ex = time.time() - t0
        k = "staggered magnetisation"
        from qiskit.transpiler import generate_preset_pass_manager
        from qiskit_ibm_runtime.fake_provider import FakeFez
        pm = generate_preset_pass_manager(backend=FakeFez(), optimization_level=3, seed_transpiler=7)
        conv = {}
        for dt in DT_SWEEP:
            c_end = pm.run(trotter_circuit(N, J, DELTA, T_MAX, steps_for(T_MAX, dt)))
            ops = c_end.count_ops()
            conv[f"{dt:.4f}"] = dict(dt=dt, max_error=max_err(ideal(N, dt)[k], r["exact"][k]), steps_at_t_max=steps_for(T_MAX, dt),
                                     two_qubit_at_t_max=int(ops.get("cz", 0) + ops.get("ecr", 0)), depth_at_t_max=c_end.depth())
        ok = [v["dt"] for v in conv.values() if v["max_error"] <= ERR_TARGET]
        DT = max(ok) if ok else min(DT_SWEEP)
        r["circuit"] = ideal(N, DT)
        r["ibm"], r["ibm_std"], stats, layout = ibm_noise(N, DT); t_nz = time.time() - t0 - t_ex
        out["sizes"][N] = dict(
            dt_chosen_us=DT, seconds=dict(exact=round(t_ex, 1), circuits_and_noise=round(t_nz, 1)),
            max_error_circuit_vs_exact=max_err(r["circuit"][k], r["exact"][k]),
            max_error_noise_only=max_err(r["ibm"][k], r["circuit"][k]),
            max_error_ibm_vs_exact=max_err(r["ibm"][k], r["exact"][k]),
            dt_convergence=conv, gate_stats=stats, physical_qubits=layout,
            series={kk: {name: r[name][kk] for name in ("exact", "circuit", "ibm", "ibm_std")} for kk in r["exact"]})
        results[N] = r
        z = out["sizes"][N]
        print(f"{N} spins: dt sweep (dt us, max err, 2q gates at t_max): " +
              ", ".join(f"({v['dt']:.4f}, {v['max_error']:.3f}, {v['two_qubit_at_t_max']})" for v in conv.values()), flush=True)
        print(f"   chosen dt {DT:.4f} us -> circuit vs exact {z['max_error_circuit_vs_exact']:.3f}; ibm_fez noise adds "
              f"{z['max_error_noise_only']:.3f}; 2q gates at t_max {stats[-1]['two_qubit']}, depth {stats[-1]['depth']}; "
              f"qubits {layout}; {z['seconds']}", flush=True)
    out["model"]["dt_us"] = DT
    os.makedirs(os.path.join(ROOT, "data", "ibm"), exist_ok=True)
    json.dump(out, open(os.path.join(ROOT, "data", "ibm", "step1.json"), "w"), indent=1)
    chart(results, os.path.join(ROOT, "output", "ibm_step1.png"))
    print("wrote data/ibm/step1.json and output/ibm_step1.png")


if __name__ == "__main__":
    main()
