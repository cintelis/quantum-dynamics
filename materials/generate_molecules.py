"""
New spacer molecules for custom synthesis (run in WSL: needs RDKit + SciPy).

    ~/cudaq-env/bin/python materials/generate_molecules.py

Builds candidate organic spacer cations from parts that work in published perovskite cells:
    RP (one charged end):  NH3+ - (CH2)k - core                k = 0..3
    DJ (two charged ends): NH3+ - (CH2)k - core-diyl - (CH2)k' - NH3+,  or  NH3+ - (CH2)m - NH3+
then scores each one:
    design rules        double-ended, aromatic, fluorinated, short, rigid           (0-28)
    evidence            similarity to spacers reported in devices x their best PCE  (0-30)
    funnel              predicted energy funnelling for (S)FA4Pb5I16 (funnel.py)   (0-22)
    ease of synthesis   RDKit synthetic-accessibility score (1 easy .. 10 hard)     (0-20)
and marks whether the free amine is already a known compound in PubChem (known = a route
very likely exists; the iodide salt is then a one-step HI neutralisation).

Inputs:  data/explorer.json (catalogue cations + published-device stats)
Output:  data/new_molecules.json
"""
import json
import os
import sys
import time
import types
import urllib.parse
import urllib.request

import numpy as np
from rdkit import Chem, DataStructs, RDConfig, RDLogger
from rdkit.Chem import AllChem, rdFingerprintGenerator, rdMolDescriptors
from rdkit.Chem.Draw import rdMolDraw2D
from rdkit.Chem.MolStandardize import rdMolStandardize

RDLogger.DisableLog("rdApp.*")
sys.path.append(os.path.join(RDConfig.RDContribDir, "SA_Score"))
import sascorer  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)
import funnel  # noqa: E402

DATA = os.path.join(ROOT, "data")
CACHE = os.path.join(DATA, "pubchem_smiles_cache.json")
FPGEN = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)

# ---------------------------------------------------------------- building blocks
# Single-ended cores: (name, SMILES starting at the attachment atom, family)
CORES = [
    ("phenyl", "c1ccccc1", "aromatic"),
    ("2-fluorophenyl", "c1ccccc1F", "fluoro-aromatic"),
    ("3-fluorophenyl", "c1cccc(F)c1", "fluoro-aromatic"),
    ("4-fluorophenyl", "c1ccc(F)cc1", "fluoro-aromatic"),
    ("2,4-difluorophenyl", "c1ccc(F)cc1F", "fluoro-aromatic"),
    ("3,4-difluorophenyl", "c1ccc(F)c(F)c1", "fluoro-aromatic"),
    ("3,5-difluorophenyl", "c1cc(F)cc(F)c1", "fluoro-aromatic"),
    ("2,6-difluorophenyl", "c1c(F)cccc1F", "fluoro-aromatic"),
    ("pentafluorophenyl", "c1c(F)c(F)c(F)c(F)c1F", "fluoro-aromatic"),
    ("4-(trifluoromethyl)phenyl", "c1ccc(C(F)(F)F)cc1", "fluoro-aromatic"),
    ("4-chlorophenyl", "c1ccc(Cl)cc1", "halo-aromatic"),
    ("3-chlorophenyl", "c1cccc(Cl)c1", "halo-aromatic"),
    ("4-bromophenyl", "c1ccc(Br)cc1", "halo-aromatic"),
    ("4-methylphenyl", "c1ccc(C)cc1", "aromatic"),
    ("4-methoxyphenyl", "c1ccc(OC)cc1", "aromatic"),
    ("biphenyl-4-yl", "c1ccc(-c2ccccc2)cc1", "aromatic"),
    ("naphthalen-1-yl", "c1cccc2ccccc12", "aromatic"),
    ("naphthalen-2-yl", "c1ccc2ccccc2c1", "aromatic"),
    ("thiophen-2-yl", "c1cccs1", "heteroaromatic"),
    ("thiophen-3-yl", "c1ccsc1", "heteroaromatic"),
    ("5-chlorothiophen-2-yl", "c1ccc(Cl)s1", "heteroaromatic"),
    ("5-bromothiophen-2-yl", "c1ccc(Br)s1", "heteroaromatic"),
    ("5-methylthiophen-2-yl", "c1ccc(C)s1", "heteroaromatic"),
    ("benzothiophen-2-yl", "c1cc2ccccc2s1", "heteroaromatic"),
    ("furan-2-yl", "c1ccco1", "heteroaromatic"),
    ("pyridin-2-yl", "c1ccccn1", "heteroaromatic"),
    ("pyridin-3-yl", "c1cccnc1", "heteroaromatic"),
    ("pyridin-4-yl", "c1ccncc1", "heteroaromatic"),
    ("cyclohexyl", "C1CCCCC1", "alicyclic"),
    ("cyclopentyl", "C1CCCC1", "alicyclic"),
]

# Double-ended cores: (name, template with {a} and {b} = the two arm SMILES, family)
DICORES = [
    ("1,4-phenylene", "c1ccc({b})cc1", "aromatic"),
    ("1,3-phenylene", "c1cccc({b})c1", "aromatic"),
    ("2-fluoro-1,4-phenylene", "c1cc(F)c({b})cc1", "fluoro-aromatic"),
    ("tetrafluoro-1,4-phenylene", "c1c(F)c(F)c({b})c(F)c1F", "fluoro-aromatic"),
    ("thiophene-2,5-diyl", "c1ccc({b})s1", "heteroaromatic"),
    ("furan-2,5-diyl", "c1ccc({b})o1", "heteroaromatic"),
    ("pyridine-2,5-diyl", "c1ccc({b})cn1", "heteroaromatic"),
    ("biphenyl-4,4'-diyl", "c1ccc(-c2ccc({b})cc2)cc1", "aromatic"),
    ("naphthalene-2,6-diyl", "c1ccc2cc({b})ccc2c1", "aromatic"),
    ("cyclohexane-1,4-diyl", "C1CCC({b})CC1", "alicyclic"),
]


def build():
    """Yield (label, neutral amine SMILES, role, family)."""
    for name, core, fam in CORES:
        for k in range(4):
            label = {0: f"{name}ammonium", 1: f"{name}methylammonium",
                     2: f"2-({name})ethylammonium", 3: f"3-({name})propylammonium"}[k]
            yield label, "N" + "C" * k + core, "RP spacer", fam
    # fluoroalkyl and ether chains (one charged end)
    for k in (1, 2, 3):
        yield f"{['', '2,2,2-trifluoroethyl', '3,3,3-trifluoropropyl', '4,4,4-trifluorobutyl'][k]}ammonium", "N" + "C" * k + "C(F)(F)F", "RP spacer", "fluoroalkyl"
        yield f"{['', '2,2,3,3,3-pentafluoropropyl', '3,3,4,4,4-pentafluorobutyl', '4,4,5,5,5-pentafluoropentyl'][k]}ammonium", "N" + "C" * k + "C(F)(F)C(F)(F)F", "RP spacer", "fluoroalkyl"
    yield "3,3,4,4,5,5,6,6,6-nonafluorohexylammonium", "NCCC(F)(F)C(F)(F)C(F)(F)C(F)(F)F", "RP spacer", "fluoroalkyl"
    yield "2-methoxyethylammonium", "NCCOC", "RP spacer", "ether"
    yield "2-(2-methoxyethoxy)ethylammonium", "NCCOCCOC", "RP spacer", "ether"
    for m in range(3, 13):
        yield f"n-{['', '', '', 'propyl', 'butyl', 'pentyl', 'hexyl', 'heptyl', 'octyl', 'nonyl', 'decyl', 'undecyl', 'dodecyl'][m]}ammonium", "N" + "C" * m, "RP spacer", "alkyl"
    # double-ended
    for name, tpl, fam in DICORES:
        for ka, kb in ((0, 0), (1, 1), (2, 2), (0, 1), (1, 2)):
            arm_b = "C" * kb + "N"
            smi = "N" + "C" * ka + tpl.format(b=arm_b)
            lk = {0: "", 1: "methyl", 2: "ethyl"}
            label = (f"{name}-bis({lk[ka]}ammonium)" if ka == kb and ka else
                     f"{name}diammonium" if ka == kb == 0 else f"{name} ({lk[ka] or 'direct'}/{lk[kb] or 'direct'} arms) diammonium")
            yield label, smi, "DJ spacer", fam
    for m in range(2, 11):
        yield f"{['', '', 'ethane', 'propane', 'butane', 'pentane', 'hexane', 'heptane', 'octane', 'nonane', 'decane'][m]}-1,{m}-diammonium", "N" + "C" * m + "N", "DJ spacer", "alkyl"
    yield "3,6-dioxaoctane-1,8-diammonium", "NCCOCCOCCN", "DJ spacer", "ether"
    yield "3-oxapentane-1,5-diammonium", "NCCOCCN", "DJ spacer", "ether"
    yield "2,2,3,3-tetrafluorobutane-1,4-diammonium", "NCC(F)(F)C(F)(F)CN", "DJ spacer", "fluoroalkyl"


# ---------------------------------------------------------------- helpers
UNCHARGER = rdMolStandardize.Uncharger()


def neutral_key(smiles):
    """Canonical SMILES of the largest N-containing fragment, neutralised (salt-insensitive)."""
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        return None
    frags = [f for f in Chem.GetMolFrags(m, asMols=True) if any(a.GetSymbol() == "N" for a in f.GetAtoms())]
    if not frags:
        return None
    f = UNCHARGER.uncharge(max(frags, key=lambda f: f.GetNumHeavyAtoms()))
    return Chem.MolToSmiles(f)


def length_A(mol):
    try:
        mh = Chem.AddHs(mol)
        if AllChem.EmbedMolecule(mh, randomSeed=42) == 0:
            AllChem.MMFFOptimizeMolecule(mh)
            P = mh.GetConformer().GetPositions()[[a.GetIdx() for a in mh.GetAtoms() if a.GetAtomicNum() > 1]]
            return float(np.max(np.linalg.norm(P[:, None] - P[None], axis=-1)))
    except Exception:
        pass
    return 1.25 * float(np.max(Chem.GetDistanceMatrix(mol)))


def svg(mol):
    """Small dark-theme structure drawing (drawn as the ammonium cation)."""
    m = Chem.RWMol(mol)
    for a in m.GetAtoms():  # protonate primary amines -> NH3+ for display
        if a.GetSymbol() == "N" and not a.GetIsAromatic() and a.GetTotalNumHs() == 2 and a.GetDegree() == 1:
            a.SetFormalCharge(1); a.SetNumExplicitHs(3); a.SetNoImplicit(True)
    m = m.GetMol(); Chem.SanitizeMol(m)
    d = rdMolDraw2D.MolDraw2DSVG(320, 190)
    o = d.drawOptions()
    o.minFontSize = 18          # atom labels stay readable in the table
    o.maxFontSize = 24
    o.fixedBondLength = 30      # keeps small molecules from being drawn huge with tiny-looking labels
    rdMolDraw2D.SetDarkMode(o)
    o.setBackgroundColour((0.08, 0.08, 0.08, 1))
    o.bondLineWidth = 2
    o.padding = 0.08
    rdMolDraw2D.PrepareAndDrawMolecule(d, m)
    d.FinishDrawing()
    return d.GetDrawingText().replace("<?xml version='1.0' encoding='iso-8859-1'?>\n", "")


def pubchem_cid(smiles, cache):
    if smiles in cache:
        return cache[smiles]
    cid = None
    url = ("https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/smiles/cids/JSON?smiles="
           + urllib.parse.quote(smiles, safe=""))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "quantum-lab-explorer/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            ids = json.load(r).get("IdentifierList", {}).get("CID", [])
            cid = ids[0] if ids and ids[0] else None
    except urllib.error.HTTPError as e:
        cid = None if e.code == 404 else "error"
    except Exception:
        cid = "error"
    finally:
        time.sleep(0.22)  # stay under PubChem's 5 requests/second
    if cid != "error":
        cache[smiles] = cid
    return None if cid == "error" else cid


def design_points(role, d, fam):
    pts, notes = 0, []
    if role == "DJ spacer":
        pts += 6; notes.append("double-ended (DJ): no van der Waals gap, usually more stable")
    if d["aromatic_rings"]:
        pts += 6; notes.append("aromatic: better charge transport between layers")
    if d["fluorine"]:
        pts += 5; notes.append("fluorinated: more water-repellent, better moisture stability")
    if d["length_A"] <= 8:
        pts += 5; notes.append(f"short ({d['length_A']} Å): thinner insulating barrier")
    elif d["length_A"] > 12:
        notes.append(f"long ({d['length_A']} Å): thick insulating barrier")
    if d["rot_bonds"] <= 3:
        pts += 3; notes.append("rigid: fewer vibrational losses")
    if fam == "heteroaromatic":
        pts += 3; notes.append("sulfur/oxygen/nitrogen ring: can interact with lead and passivate defects")
    return min(pts, 28), notes


# ---------------------------------------------------------------- main
def main():
    exp = json.load(open(os.path.join(DATA, "explorer.json"), encoding="utf-8"))
    catalogue_keys = {}
    reported = []
    for c in exp["cations"]:
        if not (c.get("desc") and c["desc"].get("cation_smiles")):
            continue
        key = neutral_key(c["desc"]["cation_smiles"])
        catalogue_keys[key] = c["name"]
        if c["db"]["devices"] > 0 and c["db"]["best_pce"] and c["role"] != "A-site":
            m = Chem.MolFromSmiles(c["desc"]["cation_smiles"])
            reported.append((c["name"], FPGEN.GetFingerprint(m), c["db"]))
    print(f"catalogue structures: {len(catalogue_keys)} | reported spacers for evidence: {len(reported)}")

    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    seen, mols = set(), []
    for label, smi, role, fam in build():
        m = Chem.MolFromSmiles(smi)
        if m is None:
            print("  invalid:", label, smi)
            continue
        key = Chem.MolToSmiles(m)
        if key in seen:
            continue
        seen.add(key)
        if key in catalogue_keys:
            continue  # already sold; not a custom-synthesis target
        d = {
            "heavy_atoms": m.GetNumHeavyAtoms(),
            "rot_bonds": rdMolDescriptors.CalcNumRotatableBonds(m),
            "aromatic_rings": rdMolDescriptors.CalcNumAromaticRings(m),
            "fluorine": sum(1 for a in m.GetAtoms() if a.GetSymbol() == "F"),
            "length_A": round(length_A(m), 2),
            "mw_amine": round(rdMolDescriptors.CalcExactMolWt(m), 2),
        }
        if not (3.5 <= d["length_A"] <= 16) or d["heavy_atoms"] > 24:
            continue  # too small to space sheets, or too bulky
        dj = role == "DJ spacer"
        sa = round(sascorer.calculateScore(m), 2)
        fp = FPGEN.GetFingerprint(m)
        best = max(reported, key=lambda r: DataStructs.TanimotoSimilarity(fp, r[1]))
        sim = round(DataStructs.TanimotoSimilarity(fp, best[1]), 2)
        fparams = funnel.spacer_to_params(d["length_A"], d["rot_bonds"], d["aromatic_rings"], dj)
        a = types.SimpleNamespace(halide="I", n_max=5, J=fparams["J"], gamma=fparams["gamma"],
                                  k_relax=0.02, k_nr=0.05, k_ex=0.5, t_max=20.0, steps=401)
        eff = funnel._efficiency(a)[0]
        dp, notes = design_points(role, d, fam)
        parts = {
            "design": dp,
            "evidence": round(30 * 0.8 * sim * min(best[2]["best_pce"] / 23, 1), 1),
            "funnel": round(22 * min(eff / 0.5, 1), 1),
            "ease": round(20 * float(np.clip((6.0 - sa) / 4.0, 0, 1)), 1),
        }
        n_heads = 2 if dj else 1
        mols.append({
            "label": label, "smiles": key, "role": role, "family": fam, "desc": d, "sa_score": sa,
            "salt": f"{label.replace('ammonium', 'ammonium iodide') if not dj else label + ' diiodide'}",
            "salt_mw": round(d["mw_amine"] + n_heads * 127.91, 2),  # + HI per amine
            "analogue": {"name": best[0], "similarity": sim, "best_pce": best[2]["best_pce"], "devices": best[2]["devices"]},
            "funnel": dict(fparams, efficiency=round(eff, 3)), "design_notes": notes,
            "parts": parts, "score": round(sum(parts.values()), 1),
            "formula_n5": f"(S){'' if dj else '2'}FA4Pb5I16",
        })
    print(f"generated: {len(mols)} new molecules (not in catalogue)")

    # PubChem status for every candidate (cached), drawings for every candidate
    for i, mo in enumerate(sorted(mols, key=lambda x: -x["score"]), 1):
        mo["pubchem_cid"] = pubchem_cid(mo["smiles"], cache)
        mo["svg"] = svg(Chem.MolFromSmiles(mo["smiles"]))
        if i % 40 == 0:
            print(f"  PubChem {i}/{len(mols)}", flush=True)
            json.dump(cache, open(CACHE, "w"))
    json.dump(cache, open(CACHE, "w"))

    mols.sort(key=lambda x: -x["score"])
    out = {
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "method": "fragment assembly (ammonium head + CH2 linker + core), scored on design rules, "
                  "similarity to reported spacers, predicted funnel efficiency (n=5, FA, iodide) and RDKit SA score",
        "counts": {"total": len(mols), "known_in_pubchem": sum(1 for m in mols if m["pubchem_cid"]),
                   "not_in_pubchem": sum(1 for m in mols if not m["pubchem_cid"])},
        "molecules": mols,
    }
    with open(os.path.join(DATA, "new_molecules.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"saved {len(mols)} | known in PubChem: {out['counts']['known_in_pubchem']} | not in PubChem: {out['counts']['not_in_pubchem']}")
    for m in mols[:12]:
        print(f"  {m['score']:5.1f}  {m['role'][:2]}  SA {m['sa_score']:.1f}  funnel {100*m['funnel']['efficiency']:4.0f}%  "
              f"CID {m['pubchem_cid'] or '—':>10}  {m['label']}  {m['smiles']}")


if __name__ == "__main__":
    main()
