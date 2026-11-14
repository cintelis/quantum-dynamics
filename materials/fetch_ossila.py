"""
Ossila's perovskite precursor salts (public product pages):
    python materials/fetch_ossila.py
Saves data/catalogue_ossila.json in the same shape as data/catalogue.json, plus supplier, full product URL,
pack sizes and currency. Polite: one request every 4 s, identifies itself, follows robots.txt (product and
collection pages are allowed). Standard library only.
"""
import html
import json
import os
import re
import sys
import time
import urllib.request

BASE = "https://www.ossila.com"
COLLECTION = "/collections/perovskite-precursor-materials"
UA = "qtumdynamics-catalogue/1.0 (+https://qtumdynamics.com; research tool, polite crawl)"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "catalogue_ossila.json")
DELAY = 4.0
SALT = re.compile(r"(iodide|bromide|chloride)", re.I)
METAL = re.compile(r"^(lead|tin|bismuth|antimony|silver|copper|germanium|caesium|cesium|rubidium|potassium|sodium|lithium)", re.I)
CAS = re.compile(r"CAS[^0-9]{0,40}?(\d{2,7}-\d{2}-\d)")


def get(path, as_json=False, tries=4):
    for k in range(tries):
        req = urllib.request.Request(BASE + path, headers={"User-Agent": UA, "Accept": "application/json" if as_json else "text/html"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", "replace")
            time.sleep(DELAY)
            return json.loads(body) if as_json else body
        except urllib.error.HTTPError as e:
            if e.code == 429 and k < tries - 1:          # rate limited: back off and try again
                wait = 30 * (k + 1)
                print(f"  429 on {path}, waiting {wait} s", flush=True)
                time.sleep(wait)
                continue
            raise


def handles():
    seen, page = [], 1
    while page <= 20:
        try:
            body = get(COLLECTION if page == 1 else f"{COLLECTION}?page={page}")
        except urllib.error.HTTPError as e:
            print(f"  stopping at page {page}: HTTP {e.code}", flush=True)
            break
        found = [h for h in re.findall(r'href="(?:/collections/[^/"]+)?/products/([a-z0-9\-]+)', body) if SALT.search(h)]
        new = [h for h in dict.fromkeys(found) if h not in seen]
        print(f"  page {page}: {len(new)} new salt products", flush=True)
        if not new:
            break
        seen += new
        page += 1
    return seen


def main():
    hs = handles()
    if not hs:
        print("no products found (the shop may be rate-limiting this address); nothing saved, try again later")
        return 1
    first = get(f"/products/{hs[0]}") if hs else ""
    m = re.search(r'og:price:currency"\s+content="([A-Z]{3})"', first) or re.search(r'"priceCurrency"\s*:\s*"([A-Z]{3})"', first)
    currency = m.group(1) if m else None
    products = []
    for i, h in enumerate(hs, 1):
        try:
            p = get(f"/products/{h}.js", as_json=True)
        except Exception as e:
            print(f"  skip {h}: {e}", flush=True)
            continue
        title = html.unescape(p["title"]).strip()
        if METAL.match(title) or not SALT.search(title):
            continue
        desc = re.sub(r"<[^>]+>", " ", p.get("description") or "")
        cas = CAS.search(desc)
        vs = p.get("variants") or []
        prices = [v["price"] / 100 for v in vs if v.get("price")]
        products.append({
            "id": f"ossila-{p['id']}", "sku": (vs[0].get("sku") or "").split("-")[0] if vs else "",
            "name": title, "cas": cas.group(1) if cas else None,
            "fromPrice": min(prices) if prices else None, "price": None,
            "inStock": any(v.get("available") for v in vs),
            "packs": [v.get("title") for v in vs if v.get("title") and v.get("title") != "Default Title"],
            "url": f"{BASE}/products/{h}",
        })
        if i % 10 == 0:
            print(f"  {i}/{len(hs)}", flush=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"supplier": "Ossila", "source": BASE + COLLECTION, "currency": currency,
                   "fetched": time.strftime("%Y-%m-%d"), "products": products}, f, ensure_ascii=False, indent=0)
    print(f"saved {len(products)} Ossila salts ({currency}) -> {os.path.normpath(OUT)}")


if __name__ == "__main__":
    sys.exit(main())
