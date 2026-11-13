# Qtum Dynamics: open tools for perovskite solar materials

Live at **https://qtumdynamics.com** (free sign-up). This repository is the whole site:

- **Materials explorer** (`/explorer`): purchasable perovskite recipes ranked against the published record of
  real devices (`materials/build_explorer.py`).
- **New molecules** (`/molecules`): generated spacer cations for custom synthesis, scored with an energy-funnel
  model and RDKit, checked against PubChem (`materials/generate_molecules.py`).
- **Live dynamics dashboard** (`/dashboard`): quantum-dynamics models on NVIDIA CUDA-Q, streamed step by step
  (`sim.py`, `funnel.py`, `transmon.py`, `dashboard.py`).
- **Spin chain at scale** (`/chain`): a 100-spin MPS run and an IBM hardware noise preview (`ibm/`).

Licensed under Apache 2.0 (see `LICENSE` and `NOTICE`). Results are model predictions, not lab measurements.

## Data

Not in this repository; rebuild or download it into `data/`:

| File | Where it comes from |
|---|---|
| `data/perovskite_db/` | [The Perovskite Database Project](https://www.perovskitedatabase.com/) (Jacobsson et al., *Nature Energy* 2022), CC BY 4.0. Download the full CSV export. |
| `data/catalogue.json` | A supplier's product catalogue, fetched by `materials/fetch_catalogue.py`. Point it at your own supplier. |
| `data/explorer.json` | `build_materials.sh` (needs the two above, RDKit and PubChem lookups). |
| `data/new_molecules.json`, `data/vibrations.json` | `generate_molecules.sh`, then `vibrations.sh`. |

Included: the spin-chain results in `data/ibm/`. Pages whose data is missing say
which script to run. Only public CAS numbers and SMILES are ever sent to PubChem.

## Hosting

`deploy/` runs the site as a hardened container behind a Cloudflare Tunnel, with a public landing page and
sign-up. See `deploy/README.md`.

---

## Quantum dynamics sandbox (CUDA-Q)

Build-your-own version of NVIDIA's blog
"Accelerating Google's QPU development with new quantum dynamics capabilities".

`sim.py` describes a quantum device once, using CUDA-Q operators, then runs it on:

| backend | where | needs |
|---|---|---|
| `cpu` | this laptop (WSL Ubuntu) | nothing extra; fine up to ~8 spins / a few hundred states |
| `gpu` | Colab, Brev or any cloud box with an NVIDIA GPU | the `dynamics` target (cuDensityMat) |
| `both` | GPU machine | runs both and prints how far apart the answers are |

Apple silicon: CUDA-Q installs and runs the CPU path, but the `dynamics` GPU solver needs an NVIDIA GPU.

## Setup (once, in WSL)
    bash setup_wsl.sh            # installs uv + CUDA-Q 0.16 into ~/cudaq-env

## Run on CPU
    bash run_cpu_demo.sh
    ~/cudaq-env/bin/python sim.py --model cavity --kappa 0.1 --chi 2
    ~/cudaq-env/bin/python sim.py --model spinchain --spins 8 --gamma 0.05 --delta 2

Plots and CSVs go to `output/`.

## Run on GPU (Google Colab, T4 runtime is enough to start)
    !pip install cudaq matplotlib
    # upload sim.py, then:
    !python sim.py --model cavity --backend both          # check CPU and GPU agree first
    !python sim.py --model spinchain --spins 12 --backend gpu --gamma 0.05

## Live dashboard
    bash start_dashboard.sh      # in WSL (or from Windows: wsl -d Ubuntu -- bash /mnt/c/code/nvidia-poc/quantum/start_dashboard.sh)
    # open http://localhost:8765

- Pick a model, a **Load** preset (Quick → Max CPU) and **Playback** (full speed or slow-motion), then **Run**.
- Every time point streams in as it is solved: one chart per measured quantity, purity of the quantum
  state, a heatmap (photon-number distribution or per-spin up/down), progress, throughput and time left.
- **Compare with** overlays any earlier run as a dashed blue baseline. Runs are saved in `output/runs/`.
- Deep link to a saved run: `http://localhost:8765/#view=<run id>&compare=<run id>`.

## Run it on an NVIDIA GPU in AWS
From PowerShell in this folder, after `aws login`:

    .\aws\gpu.ps1 up        # launches g6/g5/g4dn.xlarge (first offered) with the Deep Learning GPU AMI
    .\aws\gpu.ps1 deploy    # copies code, installs CUDA-Q, checks CPU vs GPU agree, starts the dashboard
    .\aws\gpu.ps1 tunnel    # then open http://localhost:8766 (GPU dashboard; local one stays on 8765)
    .\aws\gpu.ps1 down      # terminate when finished: GPU instances bill by the hour

SSH is allowed only from your current IP; the dashboard is reachable only through the SSH tunnel.
New AWS accounts often have a GPU quota of 0: request "Running On-Demand G and VT instances" ≥ 4 vCPUs
in Service Quotas first. On the GPU, pick backend **GPU** and the **GPU · 14 spins** preset.

## Models
- **cavity**: a superconducting qubit coupled to its readout resonator (dispersive shift `chi`,
  photon leak `kappa`, starting pulse size `alpha`). Shows how measuring the qubit destroys
  its superposition.
- **spinchain**: N interacting spins (`J`, anisotropy `delta`, dephasing noise `gamma`);
  the system the blog benchmarked at 14 qubits on one H100.

- **transmon**: the superconducting qubit from Koch et al., *Charge-insensitive qubit design derived from
  the Cooper pair box*, Phys. Rev. A 76, 042319 (2007), arXiv:cond-mat/0703002 (`transmon.py`).
  Solved exactly in the charge basis. The dashboard redraws the paper's key figures live as you move
  `E_J/E_C` (energy levels vs offset charge; charge dispersion falling exponentially; anharmonicity
  shrinking slowly), shows derived numbers (f01, α, charge dispersion, T2 limit from charge noise), and
  simulates a resonant drive including leakage to |2>. Presets: Transmon (E_J/E_C = 50), Cooper pair box
  (E_J/E_C = 1, a stray charge detunes it), Fast drive (leakage), Long run. CPU-only: a few levels.
  Simplifications: rotating-wave drive, Markovian stand-in for 1/f charge noise (A = 1e-4 e).

- **funnel**: energy funnelling in a layered (quasi-2D) perovskite solar absorber (`funnel.py`).
  Wells n = 1…n_max and the 3D bulk, coupled by J, dephased by γ, with losses and extraction. The
  what-if sweeps show noise-assisted transport (efficiency peaks at intermediate γ). Units: meV, ps.
  **Disordered film** (set "Film patches" > 0, or the "Disordered film · 50 patches" preset): a random but
  reproducible cross-section of grains (thin n near the substrate, 3D near the top), each energy shifted by
  Gaussian disorder σ, couplings J·(d0/r)³ between nearby grains. Light starts spread over all n = 1 grains.
  The extras report the *eventual* efficiency (t → ∞) against the ideal staircase, solved directly from the
  master equation in ~20 ms (exact; checked against a brute-force solve). 50 patches = 52 states, ~11 s live run.
  `start_dashboard.sh` pins OpenBLAS to 8 threads: WSL's default 22 made linear algebra ~10x slower.

## Spacer vibrations (GFN2-xTB)
`bash setup_xtb.sh` (once) installs `tblite` (GFN2-xTB, Grimme group) + ASE into ~/cudaq-env.
`bash vibrations.sh` computes, for the 6 round-1 spacers and every generated molecule (173 total, ~2 min on 8
cores), the NH3+ cation's vibrations in implicit water: frequencies, IR intensities and the share of each
vibration on the NH3+ head groups. Output `data/vibrations.json`; shown as a chart in the detail panel on
/molecules and /explorer ("Vibrations vs film energy steps"). Unstable (imaginary) modes are removed by
nudging along them and re-optimising.
First result: every spacer has vibrations near the small steps (50, 100, 140 meV); none has any within 10 meV
of the two big steps (n=1→2 at 230 meV, n=5→3D at 330 meV). Those fall in the gap between double-bond
stretches and C–H stretches, so they can't be bridged by one spacer vibration. GFN2-xTB frequencies are
typically within 5–10% of experiment (the NH3+ bend reads ~7% low): check against FTIR/Raman.

## IBM quantum computer: spin chain (step 1 done, local only)
`bash setup_qiskit.sh` (once) installs Qiskit 2.6, Aer and qiskit-ibm-runtime into ~/cudaq-env.
`ibm/spinchain_qiskit.py` builds the dashboard's spin chain (H = 2πJ Σ XX+YY+ΔZZ, Néel start) as a second-order
Trotter circuit; each bond step is one exact RXX·RYY·RZZ block. `bash ibm_step1.sh` checks it for free:
- Circuit vs the dashboard solver (J = 0.5 MHz, Δ = 1, 0–1 µs): max error 0.017 with 33 ns steps (30 steps).
  The dashboard's Pauli convention makes the interaction ~4× stronger than J suggests, so 0–3 µs would need ~100+
  steps: too deep for hardware. 0–1 µs covers the collapse and first rebound.
- Same circuit with ibm_fez's recorded noise (offline snapshot, no mitigation): errors up to 0.21–0.26 by 1 µs; the
  signal flattens toward 0. Cost at 1 µs: 459 (6 spins) / 732 (9 spins) two-qubit gates.
- Output: `data/ibm/step1.json`, `output/ibm_step1.png`.
Dephasing γ can't be set on hardware (the chip's own noise plays that role), so the circuit uses γ = 0.
Step 2 (real IBM hardware) is on hold (IBM trial expired); it needs IBM_QUANTUM_TOKEN and IBM_QUANTUM_INSTANCE in .env and explicit go-ahead.

**100 spins (http://localhost:8765/chain, "Spin chain at scale").** `bash chain100.sh` runs the same chain at 100 spins with
Qiskit Aer's matrix-product-state simulator (CPU, ~1 hour: χ = 64/128/256 take 1/6/46 min). Checks: at 24 spins χ = 128 is
within 0.004 of the exact statevector run; at 100 spins χ = 128 and 256 agree within 0.01 until 0.75 µs (shaded after that).
Finding: all lengths collapse alike in ~0.15 µs; 6 and 9 spins then break away (0.4 / 0.55 µs, end echoes); 100 spins stays
within ±0.02 of zero from 0.35 µs; 24 spins tracks 100 within 0.02. Output `data/ibm/chain100.json`, `output/chain100*.png`.
The page also shows the step-1 IBM-noise preview. Aer's MPS memory pre-check assumes no compression, so the script lifts it.

## Page menu
Every page has a nine-dot menu button at the right of the top bar (`nav.js`, shared): tiles for the four pages
(dashboard, materials explorer, new molecules, spin chain at scale) and shortcuts to each dashboard model.
Keyboard: G opens it, 1–4 jump to a page, arrow keys move, Esc closes. To add a page, add it to `PAGES` in `nav.js`.

## Materials explorer (http://localhost:8765/explorer)
Ranks purchasable perovskite compositions built from the salts in a supplier catalogue.

    python materials/fetch_catalogue.py # Windows: export the catalogue app (127.0.0.1:4000) to data/catalogue.json
    bash setup_materials.sh                      # WSL, once: adds RDKit
    bash build_materials.sh                      # WSL: PubChem structures + Perovskite Database matching -> data/explorer.json

- Data: The Perovskite Database Project (Jacobsson et al., Nature Energy 2022), v1.0.1 snapshot from
  Zenodo (CC BY 4.0, devices to Feb 2020) in `data/perovskite_db/`; PubChem structures cached in
  `data/pubchem_cache.json`.
- Score (0–100) = band-gap fit to your target use + evidence from the same or most similar reported
  cation + design rules (DJ, aromatic, fluorinated, short, rigid, thicker n) + novelty. 3D candidates
  outside tolerance factor 0.8–1.0 are scaled × 0.4.
- "Simulate →" opens the funnel model with J and γ estimated from the spacer (illustrative mapping).
- Limits: band gaps are typical values per n and halide, not calculations; database matching is by
  abbreviation; it narrows the search and does not predict device efficiency.

## New molecules for custom synthesis (http://localhost:8765/molecules)
    bash generate_molecules.sh        # WSL; needs data/explorer.json -> data/new_molecules.json

Designs spacer cations that are not in the catalogue from proven parts (ammonium head + CH2 linker + core:
fluorinated/halogenated benzenes, thiophenes, furan, pyridines, naphthalenes, fluoroalkyl and ether chains,
double-ended aromatic and alkyl diammoniums). Score = design rules + similarity to spacers proven in published
devices + predicted funnel efficiency (n = 5, FA, iodide) + ease of synthesis (RDKit SA score). Each molecule
is checked against PubChem (cached in data/pubchem_smiles_cache.json). Tick molecules and download
`synthesis_request.csv` for the supplier.

## Adding your own model
Write a `model_x(a)` function that returns `H, dims, collapse_ops, observables, psi0, times`,
and register it in `MODELS`. Both backends pick it up automatically.

## Known issue (CUDA-Q 0.16)
`spin.i(0) * <boson operator>` breaks every later `to_matrix()` call in the process
("dimension for spin operator must be 2"). Use `cudaq.operators.identity(0)` instead.
