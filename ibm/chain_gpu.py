"""
Spin chain on an NVIDIA GPU with CUDA-Q: the GPU stand-in for the IBM quantum computer run.

Same model and circuit as big_chain_mps.py (J = 0.5 MHz, delta = 1, Neel start, symmetric 2nd-order Trotter
steps of 25 ns), written as a CUDA-Q kernel. The staggered magnetisation is measured at several times.

  python chain_gpu.py --check            # CPU (qpp-cpu): 9 and 12 spins vs the exact/MPS data already on disk
  python chain_gpu.py                    # GPU: statevector 24..max spins ("nvidia" target), then 100 spins (tensornet-mps)

Output: data/ibm/chain_gpu.json (times, curves, seconds per run, GPU name)
"""
import argparse
import json
import os
import subprocess
import time

import cudaq
import numpy as np
from cudaq import spin

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
J, DELTA, DT = 0.5, 1.0, 0.025
TIMES = np.round(np.arange(0, 21) * 0.05, 4)          # 0..1 us every 50 ns (2 Trotter steps)


@cudaq.kernel
def bond(a: float, delta: float, qa: cudaq.qubit, qb: cudaq.qubit):
    """exp(-i a (XX + YY + delta ZZ)) on one bond; the three terms commute."""
    h(qa); h(qb)
    x.ctrl(qa, qb); rz(2.0 * a, qb); x.ctrl(qa, qb)
    h(qa); h(qb)
    rx(1.5707963267948966, qa); rx(1.5707963267948966, qb)
    x.ctrl(qa, qb); rz(2.0 * a, qb); x.ctrl(qa, qb)
    rx(-1.5707963267948966, qa); rx(-1.5707963267948966, qb)
    x.ctrl(qa, qb); rz(2.0 * a * delta, qb); x.ctrl(qa, qb)


@cudaq.kernel
def chain(n: int, steps: int, th: float, delta: float):
    q = cudaq.qvector(n)
    for i in range(1, n, 2):
        x(q[i])
    for s in range(steps):                            # symmetric step: even(th/2), odd(th), even(th/2)
        for i in range(0, n - 1, 2):
            bond(th / 2.0, delta, q[i], q[i + 1])
        for i in range(1, n - 1, 2):
            bond(th, delta, q[i], q[i + 1])
        for i in range(0, n - 1, 2):
            bond(th / 2.0, delta, q[i], q[i + 1])


def staggered_op(n):
    op = 0
    for i in range(n):
        op += ((-1) ** i / n) * spin.z(i)
    return op


def curve(n, times):
    th = 2 * np.pi * J * DT
    op = staggered_op(n)
    out, t0 = [], time.time()
    for t in times:
        steps = int(round(t / DT))
        out.append(float(cudaq.observe(chain, op, n, steps, th, DELTA).expectation()))
        print(f"   {n} spins  t = {t:.2f} us  staggered {out[-1]:+.4f}  ({time.time() - t0:.1f} s)", flush=True)
    return out, round(time.time() - t0, 1)


def gpu_info():
    try:
        return subprocess.check_output(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], text=True).strip()
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="CPU check against data already on disk")
    ap.add_argument("--max-sv", type=int, default=0, help="largest statevector size (default: fit to GPU memory)")
    a = ap.parse_args()
    ref = json.load(open(os.path.join(ROOT, "data", "ibm", "chain100.json")))
    ref_t = np.array(ref["model"]["times_us"])

    if a.check:
        cudaq.set_target("qpp-cpu")
        for n, key in ((9, "9"), (24, None)):
            ts = TIMES[::5] if n == 24 else TIMES
            y, secs = curve(n, ts)
            exact = np.interp(ts, ref_t, ref["small_exact"][key] if key else ref["stag_24_exact"])
            print(f"{n} spins: max difference vs reference {np.max(np.abs(np.array(y) - exact)):.2e} ({secs} s)")
        return

    gpu = gpu_info()
    print("GPU:", gpu, flush=True)
    out = dict(gpu=gpu, cudaq_version=cudaq.__version__, times_us=TIMES.tolist(), statevector={}, mps={})
    path = os.path.join(ROOT, "data", "ibm", "chain_gpu.json")

    # 1) exact statevector on the GPU (fp32: 8 bytes per amplitude). Bigger N until memory runs out.
    cudaq.set_target("nvidia")
    mem_gb = float(gpu.split(",")[1].split()[0]) / 1024 if gpu else 16
    max_sv = a.max_sv or int(np.floor(np.log2(mem_gb * 0.8 * 2 ** 30 / 8)))
    for n in sorted({24, 26, 28, max_sv - 1, max_sv}):
        if n > max_sv:
            continue
        y, secs = curve(n, TIMES)
        out["statevector"][n] = dict(stag=y, seconds=secs)
        if n == 24:
            out["statevector"][n]["max_diff_vs_cpu_exact"] = float(np.max(np.abs(np.array(y) - np.array(ref["stag_24_exact"]))))
        json.dump(out, open(path, "w"), indent=1)

    # 2) 100 spins as a matrix product state on the GPU (cuTensorNet), compared with the CPU (Aer) chi = 256 run
    cudaq.set_target("tensornet-mps")
    for chi in (64, 128, 256):
        os.environ["CUDAQ_MPS_MAX_BOND"] = str(chi)
        cudaq.set_target("tensornet-mps")             # re-read the bond-dimension setting
        ts = TIMES[::5]                               # 0, 0.25, 0.5, 0.75, 1.0 us
        y, secs = curve(100, ts)
        cpu = np.interp(ts, ref_t, ref["chain_100"]["runs"]["256"]["stag"])
        out["mps"][chi] = dict(times_us=ts.tolist(), stag=y, seconds=secs, max_diff_vs_cpu_chi256=float(np.max(np.abs(np.array(y) - cpu))))
        json.dump(out, open(path, "w"), indent=1)
    print("wrote", path)


if __name__ == "__main__":
    main()
