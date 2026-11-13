"""
Vibration spectra of spacer cations with GFN2-xTB (tblite + ASE), compared with the film's energy steps.

Why: in the funnel model a spacer's vibrations are one noise number (gamma). Real spacers vibrate at
specific frequencies; a vibration that matches an energy step between layers can carry away the energy
difference and speed up the hop. This script computes, for each spacer cation (the NH3+ form that sits
in the film):
  - its vibration frequencies (meV and cm-1) and IR intensities (comparable with a lab FTIR spectrum);
  - how much of each vibration happens on the NH3+ head groups, which hydrogen-bond into the
    lead-halide layer and so couple most to the light energy travelling through it ("head share");
  - which vibrations fall within +-10 meV of each energy step in a (spacer)FA4Pb5I16 film.

Method: RDKit 3D structure -> GFN2-xTB geometry optimisation (ALPB water to stand in for the
surrounding ions) -> finite-difference Hessian and dipole derivatives (ase.vibrations.Infrared).
GFN2-xTB frequencies are typically within ~5-10% of experiment: good for screening, not final numbers.

Input:  data/explorer.json (round-1 spacers), data/new_molecules.json (top new molecules)
Output: data/vibrations.json
"""
import os
os.environ.setdefault("OMP_NUM_THREADS", "1")       # one core per molecule; molecules run in parallel
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import json
import shutil
import sys
import tempfile
import time
from multiprocessing import Pool

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
sys.path.insert(0, ROOT)

CM_PER_MEV = 8.065544
WINDOW_MEV = 10.0          # "matches a step" if within this many meV
TOP_NEW = None             # None = every generated molecule

# The six spacers in the round-1 brief (catalogue names in explorer.json).
ROUND1 = [("Phenethylammonium", "PEA", "control"), ("Butane-1,4-diammonium", "BDA", "1"),
          ("1,3-Xylylenediammonium", "m-XDA", "2"), ("4-Fluoro-Benzylammonium", "4F-BzA", "3"),
          ("1,4-Benzene diammonium", "PDA", "4"), ("n-Pentylammonium", "PeA", "5")]


def film_steps(halide="I", n_max=5):
    """Energy steps (meV) between neighbouring layers of an n_max film, thinnest first, then -> 3D."""
    import funnel
    L = funnel.LEVELS_MEV[halide]
    E = L[:n_max] + [L[-1]]
    names = [f"n={k + 1}" for k in range(n_max)] + ["3D"]
    return [dict(step=f"{names[k]} → {names[k + 1]}", meV=round(E[k] - E[k + 1], 1)) for k in range(len(E) - 1)]


def cation_from_smiles(smiles):
    """Largest fragment, neutral -> protonate every non-aromatic N that carries H (the ammonium heads)."""
    from rdkit import Chem
    from rdkit.Chem.MolStandardize import rdMolStandardize
    m = Chem.MolFromSmiles(smiles)
    m = rdMolStandardize.LargestFragmentChooser().choose(m)
    m = rdMolStandardize.Uncharger().uncharge(m)
    rw = Chem.RWMol(m)
    q = 0
    for a in rw.GetAtoms():
        if a.GetSymbol() == "N" and not a.GetIsAromatic() and a.GetFormalCharge() == 0 and a.GetTotalNumHs() >= 1:
            a.SetFormalCharge(1); a.SetNumExplicitHs(a.GetTotalNumHs() + 1); a.SetNoImplicit(True); q += 1
    m = rw.GetMol(); Chem.SanitizeMol(m)
    return Chem.MolToSmiles(m), q


def compute(job):
    """One molecule: optimise, Hessian, IR. Returns a dict (or an error dict)."""
    from rdkit import Chem
    from rdkit.Chem import AllChem
    from ase import Atoms
    from ase.optimize import BFGS
    from ase.vibrations import Infrared
    from tblite.ase import TBLite

    t0 = time.time()
    try:
        csmi, q = cation_from_smiles(job["smiles"])
        mol = Chem.AddHs(Chem.MolFromSmiles(csmi))
        if AllChem.EmbedMolecule(mol, randomSeed=7) != 0:
            raise RuntimeError("3D embedding failed")
        AllChem.MMFFOptimizeMolecule(mol, maxIters=2000)
        pos = mol.GetConformer().GetPositions()
        atoms = Atoms([a.GetSymbol() for a in mol.GetAtoms()], positions=pos)
        calc = TBLite(method="GFN2-xTB", charge=q, verbosity=0, solvation=("alpb", "water"))
        atoms.calc = calc
        def hessian():
            work = tempfile.mkdtemp(prefix="vib_")
            try:
                ir = Infrared(atoms, name=os.path.join(work, "ir"), delta=0.01, nfree=2)
                ir.run()
                ir.read()                                # fills ir.intensities
                f = ir.get_frequencies()                 # cm-1, complex for imaginary modes
                return f, np.asarray(ir.intensities, dtype=float), [ir.get_mode(i) for i in range(len(f))]
            finally:
                shutil.rmtree(work, ignore_errors=True)

        def imaginary(f):
            return [i for i, x in enumerate(f) if abs(np.imag(x)) > abs(np.real(x)) and abs(x) > 30]

        converged = BFGS(atoms, logfile=None).run(fmax=0.002, steps=2000)
        freqs, inten, modes = hessian()
        retries = 0
        while imaginary(freqs) and retries < 3:          # saddle point: push along the unstable mode, re-optimise
            u = modes[imaginary(freqs)[0]]
            atoms.positions += 0.15 * u / np.abs(u).max()
            converged = BFGS(atoms, logfile=None).run(fmax=0.002, steps=2000)
            freqs, inten, modes = hessian()
            retries += 1
        masses = atoms.get_masses()
        # head-group atoms: N+ and the H atoms on it
        head = set()
        for a in mol.GetAtoms():
            if a.GetSymbol() == "N" and a.GetFormalCharge() == 1:
                head.add(a.GetIdx()); head.update(nb.GetIdx() for nb in a.GetNeighbors() if nb.GetSymbol() == "H")
        hmask = np.array([i in head for i in range(len(atoms))])
        out = []
        n_imag = 0
        for f, I, u in zip(freqs, inten, modes):
            if abs(np.imag(f)) > 1e-6 and abs(np.imag(f)) > abs(np.real(f)):
                if abs(f) > 30:
                    n_imag += 1
                continue
            fc = float(np.real(f))
            if fc < 30:                                  # translations/rotations and numerical noise
                continue
            w = masses[:, None] * np.abs(u) ** 2         # kinetic-energy share per atom
            share = float(w[hmask].sum() / w.sum()) if w.sum() > 0 else 0.0
            out.append(dict(cm=round(fc, 1), meV=round(fc / CM_PER_MEV, 2), ir=round(float(I), 4), head=round(share, 3)))
        return dict(job, cation_smiles=csmi, charge=q, n_atoms=len(atoms), converged=bool(converged),
                    energy_eV=round(float(atoms.get_potential_energy()), 4), n_imaginary=n_imag, retries=retries,
                    modes=out, seconds=round(time.time() - t0, 1))
    except Exception as e:  # keep going; report which molecule failed and why
        return dict(job, error=f"{type(e).__name__}: {e}", seconds=round(time.time() - t0, 1))


def summarise(r, steps):
    """Per step: vibrations within the window, and the strongest head-group mode there."""
    if "error" in r:
        return r
    irmax = max([m["ir"] for m in r["modes"]] or [1]) or 1
    for m in r["modes"]:
        m["ir_rel"] = round(m["ir"] / irmax, 4)
    matches = []
    for s in steps:
        near = [m for m in r["modes"] if abs(m["meV"] - s["meV"]) <= WINDOW_MEV]
        best = max(near, key=lambda m: m["head"], default=None)
        matches.append(dict(step=s["step"], step_meV=s["meV"], n_modes=len(near),
                            best_head_share=best["head"] if best else 0.0,
                            best_meV=best["meV"] if best else None))
    r["matches"] = matches
    # Simple screening number: how many steps have a vibration nearby with real head-group motion (> 20%).
    r["head_matched_steps"] = sum(1 for m in matches if m["best_head_share"] >= 0.2)
    return r


def main():
    from rdkit import Chem
    exp = json.load(open(os.path.join(DATA, "explorer.json"), encoding="utf-8"))
    by_name = {c["name"]: c for c in exp["cations"]}
    jobs = []
    for name, abbr, slot in ROUND1:
        c = by_name.get(name)
        if not c or not c.get("smiles"):
            print("round-1 spacer missing from explorer.json:", name); continue
        jobs.append(dict(label=name, abbr=abbr, source="round-1", slot=slot, smiles=c["smiles"]))
    new = json.load(open(os.path.join(DATA, "new_molecules.json"), encoding="utf-8"))["molecules"]
    for m in sorted(new, key=lambda m: -m["score"])[:TOP_NEW]:
        jobs.append(dict(label=m["label"], abbr="", source="new", slot="", smiles=m["smiles"], score=m["score"]))
    steps = film_steps()
    print(f"{len(jobs)} molecules · GFN2-xTB (ALPB water) · film steps (meV):", [s["meV"] for s in steps], flush=True)
    t0 = time.time()
    results = []
    with Pool(min(8, len(jobs))) as pool:
        for r in pool.imap_unordered(compute, jobs):
            results.append(summarise(r, steps))
            tag = r.get("error") or f"{len(r['modes'])} modes, {r['n_imaginary']} imaginary, head-matched steps {results[-1]['head_matched_steps']}"
            print(f"  {r['seconds']:6.1f}s  {r['label'][:55]:55s} {tag}", flush=True)
    order = {j["smiles"]: i for i, j in enumerate(jobs)}
    results.sort(key=lambda r: order[r["smiles"]])
    out = dict(generated=time.strftime("%Y-%m-%d %H:%M"), method="GFN2-xTB (tblite) + ALPB(water); finite-difference "
               "Hessian and dipole derivatives (ASE). Frequencies typically within ~5-10% of experiment.",
               film="(spacer)FA4Pb5I16 iodide, n = 1..5 then 3D", window_meV=WINDOW_MEV, steps=steps,
               molecules=results)
    p = os.path.join(DATA, "vibrations.json")
    json.dump(out, open(p, "w", encoding="utf-8"), indent=1)
    print(f"wrote {p} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
