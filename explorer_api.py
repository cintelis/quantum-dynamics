"""
Server side of the materials explorer: scores, filters and pages the candidates in data/explorer.json, so the
browser only ever receives one screen of results (at most PAGE_MAX rows) instead of the whole dataset.

The score is the one the page used to compute (out of 100):
    band-gap fit 30 · evidence from similar devices 30 · design rules 28 · novelty 12
and x0.4 for a 3D candidate whose tolerance factor is outside 0.8-1.0.
"""
import json
import math
import os
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "data", "explorer.json")
PAGE_MAX = 60
A_NAMES = {"MA": "methylammonium", "FA": "formamidinium", "EA": "ethylammonium", "DMA": "dimethylammonium",
           "GU": "guanidinium", "Ace": "acetamidinium", "IM": "imidazolium", "TMA": "trimethylammonium"}

_lock = threading.Lock()
_cache = {"mtime": None, "data": None}


def data():
    """explorer.json, reloaded when the file changes; None if it has not been built."""
    try:
        m = os.path.getmtime(PATH)
    except OSError:
        return None
    with _lock:
        if _cache["mtime"] != m:
            with open(PATH, encoding="utf-8") as f:
                d = json.load(f)
            d["_by_name"] = {c["name"]: c for c in d["cations"]}
            d["_by_formula"] = {c["formula"]: c for c in d["candidates"]}
            _cache.update(mtime=m, data=d)
        return _cache["data"]


def catalogues(d):
    if "catalogues" in d["sources"]:
        return d["sources"]["catalogues"]
    c = d["sources"].get("catalogue") or {}
    return [{"supplier": "Supplier catalogue", "products": c.get("products", 0)}]


def summary():
    d = data()
    if d is None:
        return None
    cats, cands = d["cations"], d["candidates"]
    return {
        "generated": d["generated"],
        "sources": {"database": d["sources"]["database"], "structures": d["sources"]["structures"],
                    "catalogues": [{k: v for k, v in c.items() if k in ("supplier", "products", "salts", "fetched")}
                                   for c in catalogues(d)]},
        "tiles": {"products": sum(c.get("products", 0) for c in catalogues(d)),
                  "cations": len(cats), "with_structure": sum(1 for c in cats if c.get("desc")),
                  "in_db": sum(1 for c in cats if c["db"]["devices"] > 0),
                  "candidates": len(cands), "never": sum(1 for c in cands if c["combo"]["devices"] == 0)},
        "suppliers": sorted({s for c in cands for s in c.get("suppliers", [])}),
    }


def score(c, target):
    fit = 30 * math.exp(-(((c["eg_est"] - target) / 0.3) ** 2))
    sd = c.get("spacer_db") or {}
    an = c.get("analogue")
    if sd.get("devices", 0) > 0 and sd.get("best_pce"):
        evidence = 30 * min(sd["best_pce"] / 23, 1) * (1 if sd["devices"] >= 3 else 0.7)
        note = f"{c.get('spacer') or c['A']} itself: {sd['devices']} devices, best {sd['best_pce']}%"
    elif an and an.get("best_pce"):
        evidence = 30 * 0.8 * an["similarity"] * min(an["best_pce"] / 23, 1)
        note = (f"never reported; nearest reported analogue {an['name']} (similarity {an['similarity']}, "
                f"best {an['best_pce']}%)")
    else:
        evidence, note = 0.0, "no reported device or close analogue"
    design = min(28, (c.get("design") or {}).get("points") or 0)
    nd = c["combo"]["devices"]
    novelty = 12 if nd == 0 else 6 if nd <= 3 else 0
    total, warn = fit + evidence + design + novelty, None
    t = c.get("tolerance")
    if c["kind"] == "3D" and t and (t < 0.8 or t > 1.0):
        total *= 0.4
        warn = (f"Tolerance factor {t}: this cation is the wrong size for a 3D cage, so a non-perovskite phase "
                "is likely (score × 0.4)")
    r = lambda x: round(x, 2)
    return {"fit": r(fit), "evidence": r(evidence), "design": r(design), "novelty": novelty, "total": r(total),
            "evNote": note, "warn": warn}


def _num(q, k, default, lo, hi, cast=float):
    try:
        return min(hi, max(lo, cast(q.get(k, [default])[0])))
    except (TypeError, ValueError):
        return default


def query(q):
    """Filtered, scored, sorted page of candidates: {total, offset, rows}. q is parse_qs output."""
    d = data()
    if d is None:
        return None
    g = lambda k: (q.get(k, [""])[0] or "").strip()
    target = _num(q, "target", 1.75, 1.0, 3.5)
    offset = _num(q, "offset", 0, 0, 100_000, int)
    limit = _num(q, "limit", PAGE_MAX, 1, PAGE_MAX, int)
    kind, role, A, X, n, sup = g("kind"), g("role"), g("A"), g("X"), g("n"), g("supplier")
    text = g("q").lower()[:60]
    untried = g("untried") in ("1", "true", "on")
    hits = []
    for c in d["candidates"]:
        if ((kind and c["kind"] != kind) or (role and c["role"] != role) or (A and c["A"] != A and c["kind"] != "3D")
                or (X and c["X"] != X) or (n and str(c["n"]) != n) or (untried and c["combo"]["devices"] != 0)
                or (sup and sup not in c.get("suppliers", []))
                or (text and text not in f"{c['formula']} {c.get('spacer') or ''} {c['A']}".lower())):
            continue
        hits.append((score(c, target), c))
    hits.sort(key=lambda h: -h[0]["total"])
    rows = []
    for s, c in hits[offset:offset + limit]:
        row = {k: c.get(k) for k in ("formula", "kind", "spacer", "role", "A", "X", "n", "eg_est", "tolerance",
                                     "combo", "funnel", "suppliers")}
        row["s"] = s
        if c.get("funnel"):
            sd = (d["_by_name"].get(c["spacer"]) or {}).get("desc") or {}
            row["sdesc"] = {k: sd.get(k) for k in ("length_A", "rot_bonds", "aromatic_rings")}
        rows.append(row)
    return {"total": len(hits), "offset": offset, "rows": rows}


def item(q):
    """One candidate with its score and the cation it is made from (structure, products, suppliers)."""
    d = data()
    if d is None:
        return None
    c = d["_by_formula"].get((q.get("formula", [""])[0] or "")[:120])
    if not c:
        return {"error": "not found"}
    target = _num(q, "target", 1.75, 1.0, 3.5)
    if c["kind"] == "3D":
        cat = next((x for x in d["cations"] if x.get("desc") and x["name"].lower() == A_NAMES.get(c["A"])), None)
    else:
        cat = d["_by_name"].get(c.get("spacer"))
    return {"c": c, "s": score(c, target), "cat": cat}
