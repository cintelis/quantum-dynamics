"""
Step 1 (run on Windows, where the catalogue app is reachable):
    python materials\\fetch_catalogue.py [http://127.0.0.1:4000]
Saves every listed product (with specs, categories, variants) to data/catalogue.json.
Standard library only. Uses 127.0.0.1 because 'localhost' adds ~2 s per request on Windows (IPv6 first).
"""
import json
import os
import sys
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:4000").rstrip("/")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "catalogue.json")


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return json.load(r)


def main():
    items, page = [], 1
    while True:
        d = get(f"/api/products?page={page}&size=100")
        items += d["items"]
        if not d["items"] or len(items) >= d["total"]:
            break
        page += 1
    products = []
    for i, it in enumerate(items, 1):
        p = get(f"/api/products/{it['id']}")
        products.append({k: p.get(k) for k in ("id", "sku", "name", "cas", "formula", "fromPrice", "price",
                                                "inStock", "specs", "categories", "variants", "urlKey")})
        if i % 50 == 0:
            print(f"  {i}/{len(items)}", flush=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"source": BASE, "stats": get("/api/stats"), "products": products}, f, ensure_ascii=False)
    print(f"saved {len(products)} products -> {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()
