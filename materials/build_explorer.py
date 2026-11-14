"""
Steps 2-4 of the perovskite composition explorer (run in WSL: needs RDKit + SciPy).

    ~/cudaq-env/bin/python materials/build_explorer.py

Inputs
  data/catalogue.json                      purchasable salts (from fetch_catalogue.py)
  Cations sold by more than one supplier are merged by structure, so each appears once with every product.
  data/perovskite_db/Perovskite_database_content_all_data.csv
        The Perovskite Database Project, Jacobsson et al., Nature Energy 7, 107 (2022),
        snapshot v1.0.1 (Zenodo 10.5281/zenodo.5837035, CC BY 4.0), ~42k devices to Feb 2020.
  PubChem PUG REST (CAS -> structure), cached in data/pubchem_cache.json

Output
  data/explorer.json   cations with descriptors + every candidate formula with score components
"""
import csv
import json
import math
import os
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict

import numpy as np
from rdkit import Chem, DataStructs, RDLogger
from rdkit.Chem import AllChem, rdFingerprintGenerator, rdMolDescriptors

RDLogger.DisableLog("rdApp.*")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)
import funnel  # noqa: E402

DATA = os.path.join(ROOT, "data")
DB_CSV = os.path.join(DATA, "perovskite_db", "Perovskite_database_content_all_data.csv")
CACHE = os.path.join(DATA, "pubchem_cache.json")
# (file, supplier name, product page base URL or None, currency). Files that do not exist are skipped.
CATALOGUES = [
    ("catalogue.json", "Greatcell Solar Materials", "https://www.greatcellsolarmaterials.com/", "AUD"),
]

ANIONS = ["iodide", "bromide", "chloride", "thiocyanate", "tetrafluoroborate", "trifluoroacetate", "mesylate",
          "triflate", "tosylate", "acetate", "hexafluorophosphate", "cyanate", "formate"]
HALIDE = {"iodide": "I", "bromide": "Br", "chloride": "Cl"}

# Small cations that sit inside the 3D lead-halide cage; effective radii (pm), Kieslich et al. 2014
SMALL_A = {"methylammonium": ("MA", 217), "formamidinium": ("FA", 253), "ethylammonium": ("EA", 274),
           "dimethylammonium": ("DMA", 272), "guanidinium": ("GU", 278), "acetamidinium": ("Ace", 277),
           "imidazolium": ("IM", 258), "trimethylammonium": ("TMA", 292)}
R_B = {"Pb": 119}
R_X = {"I": 220, "Br": 196, "Cl": 181}

# Catalogue name -> abbreviations used in the Perovskite Database (a_ions field).
# Unmatched cations count as "not reported", which may hide reports under another abbreviation.
ALIASES = {
    "methylammonium": ["MA"], "formamidinium": ["FA"], "guanidinium": ["GU", "GA"], "ethylammonium": ["EA"],
    "dimethylammonium": ["(DMA)"], "acetamidinium": ["(Ace)"],
    "butylammonium": ["BA", "(C4H9NH3)"], "n-butylammonium": ["BA", "(C4H9NH3)"],
    "iso-butylammonium": ["(iso-BA)"], "isobutylammonium": ["(iso-BA)"],
    "phenethylammonium": ["(PEA)", "PEA"],
    "4-fluoro-phenethylammonium": ["(pF1PEA)", "(pFPEA)", "(4FPEA)", "(FPEA)", "(f-PEA)", "(F-PEA)"],
    "4-fluorophenethylammonium": ["(pF1PEA)", "(pFPEA)", "(4FPEA)", "(FPEA)", "(f-PEA)", "(F-PEA)"],
    "pentafluorophenethylammonium": ["(F5PEA)"], "2,3,4,5,6-pentafluorophenethylammonium": ["(F5PEA)"],
    "4-chlorophenethylammonium": ["(Cl-PEA)"], "4-chloro-phenethylammonium": ["(Cl-PEA)"],
    "4-bromophenethylammonium": ["(Br-PEA)"],
    "5-ammonium valeric acid": ["(5-AVA)", "(AVA)", "(5-AVAI)"], "5-ammoniumvaleric acid": ["(5-AVA)", "(AVA)"],
    "4-ammonium butyric acid": ["(GABA)"],
    "hexylammonium": ["HA", "(C6H13NH3)"], "n-hexylammonium": ["HA", "(C6H13NH3)"],
    "octylammonium": ["OA", "(C8H17NH3)"], "n-octylammonium": ["OA", "(C8H17NH3)"],
    "propylammonium": ["PA", "(PA)", "(n-C3H7NH3)"], "n-propylammonium": ["PA", "(PA)", "(n-C3H7NH3)"],
    "iso-propylammonium": ["(iPA)"], "isopropylammonium": ["(iPA)"],
    "benzylammonium": ["(PMA)", "(BZA)", "Bn"], "phenylammonium": ["AN", "(Anyl)"], "anilinium": ["AN", "(Anyl)"],
    "2-thiophenemethylammonium": ["(ThMA)"],
    "propane-1,3-diammonium": ["(PDA)", "PDA", "(1.3-Pr(NH3)2)"], "1,3-propanediammonium": ["(PDA)", "PDA"],
    "butane-1,4-diammonium": ["(BDA)", "BDA", "(BdA)"], "1,4-butanediammonium": ["(BDA)", "BDA", "(BdA)"],
    "ethane-1,2-diammonium": ["(EDA)", "EDA"], "ethylenediammonium": ["(EDA)", "EDA"],
    "hexane-1,6-diammonium": ["HDA", "(HdA)"], "octane-1,8-diammonium": ["(ODA)", "(OdA)"],
    "1,4-phenylenedimethanammonium": ["(PDMA)"], "imidazolium": ["IM"],
    "cyclohexylmethylammonium": ["(CHMA)"], "2-hydroxyethylammonium": ["(HEA)"], "ethanolammonium": ["(HEA)"],
    "2,2,2-trifluoroethylammonium": ["(F3EA)", "(TFEA)"], "2-fluoroethylammonium": ["(FEA)"],
    "1-naphthylmethylammonium": ["(NMA)"], "ammonium": ["(NH4)"], "tetrabutylammonium": ["(TBA)"],
    "3-(aminomethyl)piperidinium": ["(3AMP)"], "4-(aminomethyl)piperidinium": ["(4AMP)"],
}


def norm(s):
    """Spelling-insensitive key: '4-Chloro-Phenethyl' == '4-chlorophenethyl', '[2.2.2]' == '[2,2,2]'."""
    return re.sub(r"[\s\-]", "", s.strip().lower()).replace(".", ",")


# ---------------------------------------------------------------- 1. catalogue -> cations
def _normalise_tables():
    global ALIASES, SMALL_A
    ALIASES = {norm(k): v for k, v in ALIASES.items()}
    SMALL_A = {norm(k): v for k, v in SMALL_A.items()}


def parse_catalogue():
    pat = re.compile(r"\s+(" + "|".join(ANIONS) + r")\b", re.I)
    cations, sources = {}, []
    for fname, supplier, base, cur in CATALOGUES:
        path = os.path.join(DATA, fname)
        if not os.path.exists(path):
            continue
        cat = json.load(open(path, encoding="utf-8"))
        supplier = cat.get("supplier") or supplier
        cur = cat.get("currency") or cur
        n0 = sum(len(c["products"]) for c in cations.values())
        _parse_one(cat, supplier, base, cur, pat, cations)
        sources.append({"supplier": supplier, "products": len(cat["products"]),
                        "salts": sum(len(c["products"]) for c in cations.values()) - n0,
                        "fetched": cat.get("fetched"), "currency": cur})
    return sources, cations


def _parse_one(cat, supplier, base, cur, pat, cations):
    for p in cat["products"]:
        name = re.split(r"\s*\|", p["name"])[0].strip()
        m = pat.search(name)
        if not m:
            continue
        cation = name[:m.start()].strip()
        if "(" in cation:  # "5-AVAI (5-Ammonium valeric acid" -> "5-Ammonium valeric acid"
            inner = cation.rsplit("(", 1)[1].strip()
            if len(re.sub(r"[^A-Za-z]", "", inner)) > 5:
                cation = inner
        cation = re.sub(r"\s*>?\s*99[.\d]*\s*%?", "", cation).strip()
        key = norm(cation)
        c = cations.setdefault(key, {"name": cation, "products": []})
        url = p.get("url") if str(p.get("url", "")).startswith("https://") else (base + p["urlKey"] + ".html" if base and p.get("urlKey") else None)
        c["products"].append({"supplier": supplier, "anion": m.group(1).lower(), "sku": p["sku"], "cas": p.get("cas"),
                              "price": p.get("fromPrice") or p.get("price"), "currency": cur, "inStock": p.get("inStock"),
                              "packs": p.get("packs") or [], "url": url})


def merge_by_structure(cations):
    """Two suppliers may spell one cation differently: keep one entry per structure, with every product."""
    by_smiles, out = {}, {}
    for key, c in sorted(cations.items(), key=lambda kv: -len(kv[1]["products"])):
        smi = (c.get("desc") or {}).get("cation_smiles")
        if smi and smi in by_smiles:
            keep = out[by_smiles[smi]]
            keep["products"] += c["products"]
            keep.setdefault("other_names", []).append(c["name"])
            keep["aliases"] = sorted(set(keep.get("aliases", [])) | set(ALIASES.get(key, [])))
            continue
        if smi:
            by_smiles[smi] = key
        c["aliases"] = ALIASES.get(key, [])
        out[key] = c
    return out


# ---------------------------------------------------------------- 2. PubChem structures
def pubchem_smiles(query, cache):
    if query in cache:
        return cache[query]
    smi = None
    for prop in ("SMILES", "CanonicalSMILES"):
        url = ("https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
               + urllib.parse.quote(query, safe="") + f"/property/{prop}/JSON")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "quantum-lab-explorer/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                props = json.load(r)["PropertyTable"]["Properties"][0]
            smi = props.get(prop) or props.get("SMILES") or props.get("CanonicalSMILES")
            if smi:
                break
        except Exception:
            pass
        finally:
            time.sleep(0.25)  # PubChem asks for <= 5 requests per second
    cache[query] = smi
    return smi


def describe(smiles):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    frags = Chem.GetMolFrags(mol, asMols=True)
    organic = [f for f in frags if any(a.GetSymbol() == "N" for a in f.GetAtoms())]
    if not organic:
        return None
    cat = max(organic, key=lambda f: f.GetNumHeavyAtoms())
    counter = [f for f in frags if f is not cat]
    heads = max(1, sum(1 for f in counter if f.GetNumHeavyAtoms() <= 12))  # one counter-ion per charged head
    # 3D length: largest heavy-atom distance in an embedded conformer
    length = None
    try:
        mh = Chem.AddHs(cat)
        if AllChem.EmbedMolecule(mh, randomSeed=42) == 0:
            AllChem.MMFFOptimizeMolecule(mh)
            pos = mh.GetConformer().GetPositions()
            heavy = [a.GetIdx() for a in mh.GetAtoms() if a.GetAtomicNum() > 1]
            P = pos[heavy]
            length = float(np.max(np.linalg.norm(P[:, None] - P[None], axis=-1))) if len(P) > 1 else 0.0
    except Exception:
        pass
    if length is None:
        length = 1.25 * float(np.max(Chem.GetDistanceMatrix(cat)))
    fp = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048).GetFingerprint(cat)
    return {
        "cation_smiles": Chem.MolToSmiles(cat),
        "heavy_atoms": cat.GetNumHeavyAtoms(),
        "rot_bonds": rdMolDescriptors.CalcNumRotatableBonds(cat),
        "aromatic_rings": rdMolDescriptors.CalcNumAromaticRings(cat),
        "fluorine": sum(1 for a in cat.GetAtoms() if a.GetSymbol() == "F"),
        "halogen": sum(1 for a in cat.GetAtoms() if a.GetSymbol() in ("Cl", "Br", "I")),
        "heads": heads,
        "length_A": round(length, 2),
        "_fp": fp,
    }


# ---------------------------------------------------------------- 3. Perovskite Database
def load_db():
    rows = []
    csv.field_size_limit(10 ** 8)
    with open(DB_CSV, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            a = {x.strip() for x in re.split(r"[;|]", r["Perovskite_composition_a_ions"]) if x.strip()}
            b = {x.strip() for x in re.split(r"[;|]", r["Perovskite_composition_b_ions"]) if x.strip()}
            c = {x.strip() for x in re.split(r"[;|]", r["Perovskite_composition_c_ions"]) if x.strip()}
            try:
                pce = float(r["JV_default_PCE"])
                pce = pce if 0 < pce < 30 else None
            except ValueError:
                pce = None
            rows.append((a, b, c, pce, r["Perovskite_dimension_2D"] == "True" or r["Perovskite_dimension_2D3D_mixture"] == "True"))
    return rows


def stats(pces):
    p = [x for x in pces if x is not None]
    return {"devices": len(pces), "best_pce": round(max(p), 1) if p else None,
            "median_pce": round(statistics.median(p), 1) if p else None}


# ---------------------------------------------------------------- 4. candidates
def main():
    _normalise_tables()
    sources, cations = parse_catalogue()
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    print("catalogues: " + ", ".join(f"{s_['supplier']} {s_['salts']} salts" for s_ in sources) + f" -> {len(cations)} cation names")

    for i, (key, c) in enumerate(sorted(cations.items()), 1):
        prods = sorted(c["products"], key=lambda p: (p["anion"] != "iodide", p["anion"]))
        smi = None
        for p in prods:
            if p["cas"]:
                smi = pubchem_smiles(p["cas"], cache)
                if smi:
                    c["structure_source"] = f"PubChem (CAS {p['cas']})"
                    break
        if not smi:
            smi = pubchem_smiles(f"{c['name']} {prods[0]['anion']}", cache)
            if smi:
                c["structure_source"] = "PubChem (name)"
        c["smiles"] = smi
        c["desc"] = describe(smi) if smi else None
        if i % 20 == 0:
            print(f"  structures {i}/{len(cations)}", flush=True)
            json.dump(cache, open(CACHE, "w"))
    json.dump(cache, open(CACHE, "w"))
    cations = merge_by_structure(cations)
    print(f"distinct cations after merging by structure: {len(cations)}")

    # roles
    for key, c in cations.items():
        if key in SMALL_A:
            c["role"] = "A-site"
        elif (c["desc"] and c["desc"]["heads"] >= 2) or re.search(r"diammonium|diium", key):
            c["role"] = "DJ spacer"
        else:
            c["role"] = "RP spacer"
        c["suppliers"] = sorted({p["supplier"] for p in c["products"]})
        c["halides"] = sorted({HALIDE[p["anion"]] for p in c["products"] if p["anion"] in HALIDE})

    db = load_db()
    print(f"database: {len(db)} devices")
    for c in cations.values():
        al = set(c["aliases"])
        c["db"] = stats([r[3] for r in db if r[0] & al]) if al else {"devices": 0, "best_pce": None, "median_pce": None}

    reported = [c for c in cations.values() if c["db"]["devices"] > 0 and c.get("desc")]

    def analogue(c):
        """Most similar reported cation (Morgan fingerprint Tanimoto), for unreported ones."""
        if c["db"]["devices"] > 0 or not c.get("desc"):
            return None
        best = None
        for o in reported:
            if o["role"] == "A-site" and c["role"] != "A-site":
                continue
            s = DataStructs.TanimotoSimilarity(c["desc"]["_fp"], o["desc"]["_fp"])
            if not best or s > best["similarity"]:
                best = {"name": o["name"], "similarity": round(s, 2), "best_pce": o["db"]["best_pce"]}
        return best

    for c in cations.values():
        c["analogue"] = analogue(c)

    def combo(al, a3d, x):
        return stats([r[3] for r in db if r[0] & al and a3d in r[0] and x in r[2] and "Pb" in r[1]])

    candidates = []
    small = {k: v for k, v in cations.items() if v["role"] == "A-site"}
    # quasi-2D absorbers: (S)2 A(n-1) Pb(n) X(3n+1)  [RP]  or  (S) A(n-1) Pb(n) X(3n+1)  [DJ]
    for key, c in sorted(cations.items()):
        if c["role"] == "A-site" or not c.get("desc"):
            continue
        d = c["desc"]
        dj = c["role"] == "DJ spacer"
        fp = funnel.spacer_to_params(d["length_A"], d["rot_bonds"], d["aromatic_rings"], dj)
        for A in ("MA", "FA"):
            for X in ("I", "Br"):
                if X not in c["halides"]:
                    continue  # only halides you can actually buy for this spacer
                cs = combo(set(c["aliases"]), A, X) if c["aliases"] else {"devices": 0, "best_pce": None, "median_pce": None}
                for n in (1, 2, 3, 4, 5):
                    sp = "(" + abbrev(c["name"]) + ")" + ("" if dj else "2")
                    formula = f"{sp}{A + (str(n - 1) if n > 2 else '') if n > 1 else ''}Pb{n if n > 1 else ''}{X}{3 * n + 1}"
                    candidates.append({
                        "kind": "quasi-2D", "formula": formula, "spacer": c["name"], "spacer_key": key,
                        "role": c["role"], "A": A, "X": X, "n": n,
                        "eg_est": funnel.LEVELS_MEV[X][n - 1] / 1000,
                        "combo": cs, "spacer_db": c["db"], "analogue": c["analogue"],
                        "design": design_points(c, n), "funnel": fp, "suppliers": c["suppliers"],
                    })
    # 3D: FA-based binary mixes with one other small cation from the catalogue
    for key, c in sorted(small.items()):
        ab, r = SMALL_A[key]
        for X in ("I", "Br"):
            for x in ((1.0,) if ab == "FA" else (0.15, 1.0)):
                rA = r * x + SMALL_A[norm("formamidinium")][1] * (1 - x)
                t = (rA + R_X[X]) / (math.sqrt(2) * (R_B["Pb"] + R_X[X]))
                ions = {ab} if x == 1.0 else {ab, "FA"}
                cs = stats([r_[3] for r_ in db if r_[0] == ions and X in r_[2] and "Pb" in r_[1] and len(r_[2]) == 1])
                formula = f"{ab}Pb{X}3" if x == 1.0 else f"FA{1 - x:.2f}{ab}{x:.2f}Pb{X}3"
                eg = {"I": 1.53, "Br": 2.28}[X] + (0.05 if ab == "MA" else 0.0)
                candidates.append({
                    "kind": "3D", "formula": formula, "spacer": None, "role": "A-site", "A": ab, "X": X, "n": None,
                    "eg_est": eg, "tolerance": round(t, 3), "combo": cs, "spacer_db": c["db"], "analogue": None,
                    "design": {"points": 6 if 0.8 <= t <= 1.0 else 0,
                               "notes": [f"tolerance factor {t:.3f} " + ("in 0.8–1.0: 3D cage likely" if 0.8 <= t <= 1.0 else "outside 0.8–1.0: 3D cage unlikely")]},
                    "funnel": None, "suppliers": c["suppliers"],
                })

    out = {
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "sources": {
            "catalogues": sources,
            "database": "The Perovskite Database Project (Jacobsson et al., Nature Energy 2022), v1.0.1 snapshot, CC BY 4.0",
            "structures": "PubChem PUG REST, descriptors with RDKit",
        },
        "cations": [{k: v for k, v in dict(c, desc={kk: vv for kk, vv in (c["desc"] or {}).items() if not kk.startswith("_")} if c.get("desc") else None).items()}
                    for c in sorted(cations.values(), key=lambda c: c["name"].lower())],
        "candidates": candidates,
    }
    with open(os.path.join(DATA, "explorer.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    n_struct = sum(1 for c in cations.values() if c.get("desc"))
    n_rep = sum(1 for c in cations.values() if c["db"]["devices"])
    untried = sum(1 for c in candidates if c["combo"]["devices"] == 0)
    print(f"structures found: {n_struct}/{len(cations)} | cations reported in DB: {n_rep}")
    print(f"candidates: {len(candidates)} ({untried} with no reported device for that cation/A/halide combination)")


def abbrev(name):
    """Short label for formulas: known abbreviation if we have one, else a compact name."""
    al = ALIASES.get(norm(name))
    if al:
        return al[0].strip("()")
    s = re.sub(r"-?di-?ammonium|-?1,4-diium|-?diium|ammonium", "", name, flags=re.I)
    return s.replace(" ", "").strip("-,") or name


def design_points(c, n):
    """Literature design rules, each worth a few points, with the reason shown in the UI."""
    d, pts, notes = c["desc"], 0, []
    if c["role"] == "DJ spacer":
        pts += 6; notes.append("Dion–Jacobson: no van der Waals gap, usually more stable")
    if d["aromatic_rings"]:
        pts += 6; notes.append("aromatic: better charge transport between layers")
    if d["fluorine"]:
        pts += 5; notes.append("fluorinated: more hydrophobic, better moisture stability")
    if d["length_A"] <= 8:
        pts += 5; notes.append(f"short ({d['length_A']} Å): less insulating barrier")
    elif d["length_A"] > 12:
        notes.append(f"long ({d['length_A']} Å): thick insulating barrier")
    if d["rot_bonds"] <= 3:
        pts += 3; notes.append("rigid: less vibrational loss")
    if n >= 3:
        pts += 3; notes.append(f"n = {n}: closer to the 3D band gap")
    return {"points": pts, "notes": notes}


if __name__ == "__main__":
    main()
