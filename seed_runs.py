"""
Save one reference run per model on a fresh server, so researchers find examples in the dashboard's Load list.
Uses the dashboard's own presets and its /api/run endpoint, so the runs match what pressing Run gives.

  docker compose exec dashboard python seed_runs.py          # examples already saved are skipped
  docker compose exec dashboard python seed_runs.py --force  # run them all again
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE = f"http://127.0.0.1:{os.environ.get('PORT', 8765)}"
RUNS = [("funnel", "pea"), ("funnel", "film"), ("transmon", "transmon"), ("cavity", "standard"), ("spinchain", "standard")]


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.load(r)


def run(model, preset_key, presets):
    p = {k: v for k, v in presets[model][preset_key].items() if k != "label"}
    q = urllib.parse.urlencode(dict(model=model, backend="cpu", **p))
    for attempt in range(30):                 # the server frees its one run slot just after sending "done"
        try:
            return run_once(q)
        except RuntimeError as e:
            if "in progress" not in str(e):
                raise
            time.sleep(2)
    raise RuntimeError("the server stayed busy with another run")


def run_once(q):
    t0, event = time.time(), None
    with urllib.request.urlopen(f"{BASE}/api/run?{q}", timeout=900) as r:
        for raw in r:
            line = raw.decode().strip()
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and event in ("done", "error"):
                data = json.loads(line[5:])
                if event == "error":
                    raise RuntimeError(data.get("message"))
                return data["id"], time.time() - t0
    raise RuntimeError("stream ended without a result")


def already_saved(model, preset, saved):
    want = {k: v for k, v in preset.items() if k != "label"}
    return any(r["model"] == model and r["status"] == "done" and
               all(str((r.get("params") or {}).get(k)) == str(v) or (r.get("params") or {}).get(k) == v for k, v in want.items())
               for r in saved)


def main():
    schema = get("/api/schema")["models"]
    saved = get("/api/runs")
    for model, key in RUNS:
        label = schema[model]["presets"][key]["label"]
        if already_saved(model, schema[model]["presets"][key], saved) and "--force" not in sys.argv:
            print(f"{schema[model]['title']:<32} {label:<36} already saved")
            continue
        rid, secs = run(model, key, {m: schema[m]["presets"] for m in schema})
        print(f"{schema[model]['title']:<32} {label:<36} {secs:6.1f} s  -> {rid}", flush=True)


if __name__ == "__main__":
    main()
