"""
Live dashboard for sim.py. Standard library only (plus what sim.py already needs).

    ~/cudaq-env/bin/python dashboard.py            # then open http://localhost:8765

Endpoints
  GET /                 the dashboard page
  GET /api/schema       models, their parameters, available backends
  GET /api/run?...      start a run; streams Server-Sent Events: meta, step, done, error
  GET /api/runs         saved runs (newest first)
  GET /api/runs/<id>    one saved run, full data
  DELETE /api/runs/<id> move a run to the trash (its owner or an admin)

Public site (QUANTUM_SESSION_KEY set): / is the landing page with sign-up, /dashboard the dashboard. Every page
can be viewed; running, deleting and the full molecule designs need a sign-up.
POST /api/register, /api/logout, /api/admin/login; GET /api/session, /api/admin/registrations[?format=csv].
"""
import base64
import csv
import hashlib
import hmac
import io
import json
import math
import os
import re
import secrets
import threading
import time
import types
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

import numpy as np

import explorer_api
import sim

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS_DIR = os.path.join(HERE, "output", "runs")
os.makedirs(RUNS_DIR, exist_ok=True)

# Shared server (QUANTUM_SHARED=1): Cloudflare Access adds the signed-in person's email to every request; people
# may delete their own runs, QUANTUM_ADMINS (comma-separated emails) any run, and a request without an email
# nothing. Local use (QUANTUM_SHARED unset): everything is allowed.
SHARED = os.environ.get("QUANTUM_SHARED") == "1"
# Trust that email header only while Cloudflare Access sits in front (QUANTUM_ACCESS=1). Without Access, anyone
# could send the header themselves and pose as an admin, so it is ignored and shared-mode deletes are off.
TRUST_ACCESS = os.environ.get("QUANTUM_ACCESS") == "1"
ADMINS = {e.strip().lower() for e in os.environ.get("QUANTUM_ADMINS", "").split(",") if e.strip()}
TRASH_DIR = os.path.join(RUNS_DIR, ".trash")     # deleted runs are moved here, not erased

# Public site with sign-up (QUANTUM_SESSION_KEY set): every page is open to look at; running a simulation,
# deleting a run and the full molecule designs need the signed cookie that registering gives. Emails are not verified, so a person's identity is that cookie's random id, never
# the email they typed. QUANTUM_ADMIN_KEY unlocks the admin view (all registrations, delete any run).
SESSION_KEY = os.environ.get("QUANTUM_SESSION_KEY", "").encode()
ADMIN_KEY = os.environ.get("QUANTUM_ADMIN_KEY", "")
GATED = SHARED and bool(SESSION_KEY)
REG_FILE = os.path.join(RUNS_DIR, ".registrations.jsonl")   # one JSON line per sign-up, in the runs volume
CANONICAL_HOST = os.environ.get("QUANTUM_HOST", "")          # e.g. qtumdynamics.com
REDIRECT_HOSTS = {h.strip().lower() for h in os.environ.get("QUANTUM_REDIRECT_HOSTS", "").split(",") if h.strip()}
COOKIE = "qd_session"
# Everything can be looked at without signing up; these need a sign-up (they use the server or reveal designs).
# Deleting a run (DELETE) always needs one too. /api/molecules and /api/vibrations are trimmed for visitors.
MEMBERS_ONLY = {"/api/run"}
EMAIL_RE = re.compile(r"[^@\s<>\"',;]{1,64}@[A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,24}")
RATE = {}                       # ip -> recent attempt times (sign-ups and admin logins)
RATE_LOCK = threading.Lock()


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_cookie(payload):
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return body + "." + _b64(hmac.new(SESSION_KEY, body.encode(), hashlib.sha256).digest())


def read_cookie(value):
    try:
        body, sig = value.split(".", 1)
        good = _b64(hmac.new(SESSION_KEY, body.encode(), hashlib.sha256).digest())
        return json.loads(_unb64(body)) if SESSION_KEY and hmac.compare_digest(sig, good) else None
    except Exception:
        return None


def rate_ok(ip, limit, window=3600):
    now = time.time()
    with RATE_LOCK:
        hits = [t for t in RATE.get(ip, []) if now - t < window]
        if len(hits) >= limit:
            RATE[ip] = hits
            return False
        RATE[ip] = hits + [now]
        return True

# Data endpoints are for the site's own pages, not bulk download. A visitor's browser gets a short-lived signed
# "visit" cookie with every page; /api/* answers visitors only with that cookie and the browser's same-origin
# marker (Sec-Fetch-Site), so a script calling the API directly is refused. Everyone is also rate limited per
# address: requests per 10 minutes and explorer rows per day (signed-up users get more).
VISIT_COOKIE = "qd_visit"
VISIT_TTL = 6 * 3600
API_RATE = {"visitor": 240, "member": 900}          # requests per 10 minutes
ROW_BUDGET = {"visitor": 1500, "member": 6000}      # explorer rows per 24 hours
BUDGET = {}                                         # ip -> [(time, rows)]


def make_visit():
    ts = str(int(time.time()))
    return ts + "." + _b64(hmac.new(SESSION_KEY, b"visit." + ts.encode(), hashlib.sha256).digest()[:16])


def visit_ok(token):
    try:
        ts, sig = token.split(".", 1)
        good = _b64(hmac.new(SESSION_KEY, b"visit." + ts.encode(), hashlib.sha256).digest()[:16])
        return hmac.compare_digest(sig, good) and 0 <= time.time() - int(ts) < VISIT_TTL
    except Exception:
        return False


def budget_ok(key, rows, limit, window=86400):
    now = time.time()
    with RATE_LOCK:
        used = [(t, n) for t, n in BUDGET.get(key, []) if now - t < window]
        if sum(n for _, n in used) + rows > limit:
            BUDGET[key] = used
            return False
        BUDGET[key] = used + [(now, rows)]
        return True


# One run at a time: the solver is CPU-bound, and CUDA-Q operator building has global state.
RUN_LOCK = threading.Lock()

COMMON = [
    dict(key="t_max", label="End time (µs)", default=3.0, min=0.1, max=100, step=0.1),
    dict(key="steps", label="Time points", default=301, min=11, max=10001, step=1, int=True),
]
SCHEMA = {
    "cavity": {
        "title": "Qubit + readout resonator",
        "blurb": "A qubit in superposition next to a resonator holding a light pulse. "
                 "The pulse splits depending on the qubit state; leaking photons destroy the superposition.",
        "params": COMMON + [
            dict(key="levels", label="Photon levels kept", default=15, min=4, max=120, step=1, int=True),
            dict(key="chi", label="Dispersive shift χ (MHz)", default=1.0, min=0, max=10, step=0.05),
            dict(key="kappa", label="Photon leak κ (MHz)", default=0.3, min=0, max=5, step=0.05),
            dict(key="alpha", label="Pulse amplitude α", default=2.0, min=0, max=8, step=0.1),
        ],
    },
    "transmon": {
        "title": "Transmon qubit",
        "blurb": "Koch et al. 2007: shunt a Cooper pair box with a big capacitor (raise E_J/E_C) and it stops "
                 "caring about stray charge, at a small cost in anharmonicity. Drag E_J/E_C from 1 (Cooper pair box) "
                 "to 50 (transmon), add a stray charge n_g, and drive it as a qubit.",
        "cpu_only": True,
        "params": [
            dict(key="t_max", label="End time (µs)", default=0.1, min=0.005, max=20, step=0.005),
            dict(key="steps", label="Time points", default=401, min=11, max=10001, step=1, int=True),
            dict(key="ej_ec", label="E_J / E_C", default=50, min=0.5, max=100, step=0.5,
                 help="1 = Cooper pair box · 50 = typical transmon"),
            dict(key="ec", label="Charging energy E_C (MHz)", default=250, min=50, max=1000, step=10),
            dict(key="ng", label="Stray charge n_g", default=0.1, min=0, max=0.5, step=0.01,
                 help="Drive is tuned for n_g = 0; stray charge detunes it"),
            dict(key="drive", label="Drive Ω (MHz)", default=50, min=0, max=500, step=5),
            dict(key="levels", label="Levels kept", default=4, min=2, max=8, step=1, int=True),
            dict(key="t1", label="T1 (µs)", default=30, min=0, max=1000, step=1,
                 help="Energy-loss time of the qubit. 0 = no energy loss"),
        ],
    },
    "funnel": {
        "title": "Perovskite energy funnel",
        "blurb": "Light absorbed in the thinnest layer (n = 1) of a layered perovskite must hop down an energy "
                 "staircase into the 3D bulk to be collected, racing against losses. The organic spacer sets the "
                 "coupling J (shorter = stronger) and the dephasing γ (floppier = noisier). Some noise helps.",
        "cpu_only": True, "time_unit": "ps",
        "params": [
            dict(key="t_max", label="End time (ps)", default=20, min=1, max=500, step=1),
            dict(key="steps", label="Time points", default=401, min=11, max=10001, step=1, int=True),
            dict(key="halide", label="Halide", default="I", choices=["I", "Br"]),
            dict(key="n_max", label="Thickest thin layer n", default=3, min=1, max=5, step=1, int=True),
            dict(key="J", label="Coupling J (meV)", default=8, min=0.1, max=150, step=0.1,
                 help="Shorter spacer → wells closer → larger J"),
            dict(key="gamma", label="Dephasing γ (meV)", default=60, min=0.1, max=3000, step=1,
                 help="Spacer vibrations; floppier → larger"),
            dict(key="k_nr", label="Loss rate (1/ps)", default=0.05, min=0, max=5, step=0.01),
            dict(key="k_ex", label="Extraction from 3D (1/ps)", default=0.5, min=0, max=10, step=0.05),
            dict(key="k_relax", label="Phonon hopping (1/ps)", default=0.02, min=0, max=5, step=0.01),
            dict(key="patches", label="Film patches", default=0, min=0, max=80, step=1, int=True,
                 help="0 = ideal staircase. Above 0: a disordered film of grains with mixed thickness scattered through it"),
            dict(key="sigma", label="Energy disorder σ (meV)", default=30, min=0, max=200, step=1,
                 help="Random shift of each patch's energy (only used when Film patches > 0)"),
            dict(key="seed", label="Random film #", default=1, min=1, max=999, step=1, int=True),
        ],
    },
    "spinchain": {
        "title": "Spin chain",
        "blurb": "N interacting qubits in a line, starting in an alternating up/down pattern. "
                 "The system the NVIDIA blog benchmarked for Google.",
        "params": COMMON + [
            dict(key="spins", label="Spins (qubits)", default=6, min=2, max=9, step=1, int=True,
                 help="CPU limit 9 (a 512x512 density matrix). Use the GPU backend for more."),
            dict(key="J", label="Coupling J (MHz)", default=0.5, min=0, max=5, step=0.05),
            dict(key="delta", label="ZZ anisotropy Δ", default=1.0, min=-3, max=3, step=0.1),
            dict(key="gamma", label="Dephasing γ (MHz)", default=0.05, min=0, max=2, step=0.01),
        ],
    },
}

# Load presets: same physics, more work. Times measured on this laptop's CPU (2026-11-08).
PRESETS = {
    "cavity": {
        "quick":    dict(label="Quick · ~1 s",       levels=15, alpha=2.0, t_max=3,  steps=301),
        "standard": dict(label="Standard · ~3 s",    levels=40, alpha=4.0, t_max=10, steps=1001),
        "heavy":    dict(label="Heavy · ~1 min",     levels=80, alpha=6.0, t_max=20, steps=2001, kappa=0.1),
        "max":      dict(label="Max CPU · ~8 min",   levels=120, alpha=8.0, t_max=40, steps=4001, kappa=0.05),
    },
    "transmon": {
        "transmon": dict(label="Transmon · E_J/E_C = 50", ej_ec=50, ng=0.1, drive=50, t_max=0.1, steps=401),
        "cpb":      dict(label="Cooper pair box · E_J/E_C = 1", ej_ec=1, ng=0.1, drive=50, t_max=0.1, steps=401),
        "leak":     dict(label="Fast drive → leakage to |2⟩", ej_ec=50, ng=0, drive=200, t_max=0.05, steps=801, levels=5),
        "long":     dict(label="Long run · 20 µs, T1 = 5 µs", ej_ec=20, ng=0.25, drive=5, t_max=20, steps=4001, t1=5, levels=6),
    },
    "funnel": {
        "pea":   dict(label="PEA-like spacer (J 4.5, γ 50)", J=4.53, gamma=50, n_max=3, halide="I", patches=0),
        "dj":    dict(label="Short DJ spacer (J 40, γ 60)", J=40, gamma=60, n_max=3, halide="I", patches=0),
        "quiet": dict(label="Too rigid (γ 2 meV): stuck", J=8, gamma=2, n_max=3, halide="I", patches=0),
        "noisy": dict(label="Too floppy (γ 2000 meV): Zeno", J=8, gamma=2000, n_max=3, halide="I", patches=0),
        "long":  dict(label="Long run · n up to 5, 200 ps", J=8, gamma=60, n_max=5, t_max=200, steps=2001, halide="I", patches=0),
        "film":  dict(label="Disordered film · 50 patches", J=8, gamma=60, n_max=3, halide="I", patches=50, sigma=30, t_max=20, steps=201),
    },
    "spinchain": {
        "quick":    dict(label="Quick · ~1 s",       spins=6, t_max=3,  steps=301),
        "standard": dict(label="Standard · ~20 s",   spins=8, t_max=4,  steps=401),
        "heavy":    dict(label="Heavy · ~1 min",     spins=9, t_max=6,  steps=201),
        "max":      dict(label="Max CPU · ~3 min",   spins=9, t_max=20, steps=1001, gamma=0.02),
        "gpu":      dict(label="GPU · 14 spins",     spins=14, t_max=6, steps=301),
    },
}
# Plain-language "?" tip for every parameter (shown next to its title on the dashboard).
_RUN = {"t_max": "How far in simulated time the run goes. Longer runs take proportionally longer to compute.",
        "steps": "How many moments the charts record between 0 and the end time. More points: smoother curves, slower run."}
HELP = {
    "cavity": {**_RUN,
        "levels": "How many photon-number states the simulation keeps for the resonator. Keep it well above the pulse's "
                  "average photon count (α²); more levels = slower.",
        "chi": "How much the qubit's state shifts the resonator's frequency. Larger χ splits the pulse faster, so the "
               "qubit is read out faster.",
        "kappa": "Rate photons leak out of the resonator. Leaked photons carry away which-state information, which "
                 "destroys the qubit's superposition.",
        "alpha": "Size of the light pulse in the resonator; its average photon count is α². Bigger pulses read out "
                 "faster but need more photon levels."},
    "transmon": {**_RUN,
        "ej_ec": "Ratio of Josephson energy to charging energy. 1 = Cooper pair box (very sensitive to stray charge) · "
                 "50 = typical transmon (almost insensitive).",
        "ec": "Energy to add one electron charge to the island. Sets the anharmonicity: the gap between the 0→1 and "
              "1→2 transitions. Typical: 200–300 MHz.",
        "ng": "Stray offset charge on the island, in units of 2e. The drive is tuned for n_g = 0; stray charge detunes it.",
        "drive": "Strength of the microwave drive (Rabi rate). Too strong compared with the anharmonicity and population "
                 "leaks into level |2⟩.",
        "levels": "How many transmon energy levels the simulation keeps. 4 is enough to see leakage; more is slower."},
    "funnel": {
        "t_max": "How long the simulated energy transfer runs, in picoseconds (1 ps = a millionth of a microsecond).",
        "steps": _RUN["steps"],
        "halide": "I = iodide, Br = bromide. Sets the energy of each layer: bromide layers sit higher.",
        "n_max": "Thickest thin layer in the film: wells n = 1 up to this value, then the 3D bulk. Each step down in "
                 "energy is one hop for the light energy.",
        "J": "How strongly neighbouring layers exchange energy. Shorter spacer → wells closer → larger J.",
        "gamma": "Random jostling of each layer's energy by spacer vibrations; floppier spacers → larger. Some helps energy "
                 "hop down the steps; too much freezes it in place.",
        "k_nr": "Rate light energy is lost as heat in any layer (non-radiative recombination). Lower = better film quality.",
        "k_ex": "Rate the 3D bulk hands charges on to the electrodes, where they count as collected.",
        "k_relax": "Rate of downhill hops helped by lattice vibrations (phonons), on top of the quantum coupling J. "
                   "Uphill hops are suppressed by temperature (300 K).",
        "seed": "Picks a different random film layout with the same statistics. Only used when Film patches > 0."},
    "spinchain": {**_RUN,
        "spins": "Number of qubits in the chain. CPU limit 9 (a 512 × 512 density matrix); use the GPU backend for more.",
        "J": "How strongly neighbouring spins swap their up and down states (the flip-flop rate).",
        "delta": "Strength of the extra Z–Z interaction relative to J. Δ = 0: XY chain · Δ = 1: Heisenberg chain · "
                 "large Δ: the alternating pattern stays frozen in place.",
        "gamma": "Noise on every spin that scrambles quantum coherence over time (dephasing)."},
}
for m in SCHEMA:
    SCHEMA[m]["params"] = [dict(p) for p in SCHEMA[m]["params"]]   # COMMON is shared: copy before editing
    for p in SCHEMA[m]["params"]:
        if p["key"] in HELP.get(m, {}):
            p["help"] = HELP[m][p["key"]]
missing = [(m, p["key"]) for m in SCHEMA for p in SCHEMA[m]["params"] if not p.get("help")]
assert not missing, f"parameters without a tip: {missing}"
for m in SCHEMA:
    SCHEMA[m]["presets"] = PRESETS[m]


def gpu_available():
    try:
        return sim.cudaq.num_available_gpus() > 0
    except Exception:
        return False


GPU = gpu_available()


def parse_params(model, backend, q):
    a = {}
    for p in SCHEMA[model]["params"]:
        if "choices" in p:
            v = q.get(p["key"], [p["default"]])[0]
            a[p["key"]] = v if v in p["choices"] else p["default"]
            continue
        v = float(q.get(p["key"], [p["default"]])[0])
        if not math.isfinite(v):
            raise ValueError(f"{p['key']} must be a number")
        hi = 14 if (p["key"] == "spins" and backend == "gpu") else p["max"]  # GPU can go bigger
        v = min(max(v, p["min"]), hi)
        a[p["key"]] = int(round(v)) if p.get("int") else v
    return a


EXTRAS = {
    "transmon": lambda a: (sim.transmon.static_charts(a.ej_ec, a.ec), sim.transmon.derived_tiles(a)),
    "funnel": lambda a: (sim.funnel.static_charts(a), sim.funnel.derived_tiles(a)),
}


def extras(model, a):
    static, derived = EXTRAS[model](a)
    return {"static": static, "derived": derived}


def make_args(model, backend, q):
    """Parsed numeric/choice params plus optional free-text spacer labels (from the explorer)."""
    a = types.SimpleNamespace(**parse_params(model, backend, q))
    a.spacer_name = q.get("spacer", [""])[0][:80]
    a.spacer_note = q.get("spacer_note", [""])[0][:120]
    return a


def run_id(model):
    return time.strftime("%Y%m%d-%H%M%S") + f"{int(time.time() * 1000) % 1000:03d}_{model}"


class Handler(BaseHTTPRequestHandler):
    server_version = "QuantumDash/1.0"

    def session(self):
        """Who is asking: {"id", "n" (name), "a" (admin)} from the sign-up cookie, or None."""
        c = SimpleCookie()
        try:
            c.load(self.headers.get("Cookie") or "")
        except Exception:
            pass
        s = read_cookie(c[COOKIE].value) if COOKIE in c else None
        if s is None and TRUST_ACCESS:     # behind Cloudflare Access, its verified email header
            e = (self.headers.get("Cf-Access-Authenticated-User-Email") or "").strip().lower()
            s = {"id": e, "n": e.split("@")[0], "a": int(e in ADMINS)} if e else None
        return s

    def user(self):
        s = self.session()
        return s["id"] if s else None

    def can_delete(self, owner):
        if not SHARED:
            return True
        s = self.session()
        return bool(s) and (bool(s.get("a")) or (owner is not None and owner == s["id"]))

    def client_ip(self):
        return self.headers.get("CF-Connecting-IP") or self.client_address[0]

    def host_redirect(self, code=301):
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        if not (CANONICAL_HOST and host in REDIRECT_HOSTS):
            return False
        self.send_response(code)
        self.send_header("Location", f"https://{CANONICAL_HOST}{self.path}")
        self.send_header("Content-Length", "0")
        self.end_headers()
        return True

    def member(self):
        """Signed up (or not a sign-up server, or a local call such as the healthcheck and seed_runs)."""
        return not GATED or self.client_address[0] in ("127.0.0.1", "::1") or bool(self.session())

    def gate(self, path, members=False):
        """True if this request may go on; otherwise it is answered here (to the sign-up form, or 401)."""
        if not (members or path in MEMBERS_ONLY) or self.member():
            return True
        if path.startswith("/api/"):
            self.send_json({"error": "Sign up on the home page to use this.", "signup": "/#signup"}, 401)
        else:
            self.send_response(302)
            self.send_header("Location", "/?next=" + quote(path) + "#signup")
            self.send_header("Content-Length", "0")
            self.end_headers()
        return False

    def cookie(self, name):
        c = SimpleCookie()
        try:
            c.load(self.headers.get("Cookie") or "")
        except Exception:
            return None
        return c[name].value if name in c else None

    def api_ok(self, path):
        """Data requests: from this site's pages, within the rate limit. Answers and returns False otherwise."""
        if not GATED or not path.startswith("/api/") or path == "/api/session" or self.client_address[0] in ("127.0.0.1", "::1"):
            return True
        who = "member" if self.session() else "visitor"
        if who == "visitor":
            if self.headers.get("Sec-Fetch-Site") != "same-origin" or not visit_ok(self.cookie(VISIT_COOKIE) or ""):
                self.send_json({"error": "This data is shown on the site's pages; open https://" + (CANONICAL_HOST or "the site") +
                                " in a browser. The code that builds it is open source."}, 403)
                return False
        if not rate_ok("api:" + self.client_ip(), API_RATE[who], 600):
            self.send_json({"error": "Too many requests from this address. Please wait a few minutes."}, 429)
            return False
        return True

    def rows_ok(self, n):
        who = "member" if self.session() or not GATED or self.client_address[0] in ("127.0.0.1", "::1") else "visitor"
        if budget_ok("rows:" + self.client_ip(), n, ROW_BUDGET[who]):
            return True
        self.send_json({"error": "Daily browsing limit reached for this address." +
                        (" Sign up (free) for a higher limit." if who == "visitor" else " Please come back tomorrow.")}, 429)
        return False

    def same_origin(self):
        o = self.headers.get("Origin")
        return not o or urlparse(o).netloc.lower() == (self.headers.get("Host") or "").lower()

    def cookie_header(self, payload, max_age=34_000_000):   # about 13 months
        secure = "; Secure" if (CANONICAL_HOST or self.headers.get("X-Forwarded-Proto") == "https") else ""
        value = make_cookie(payload) if payload else ""
        return f"{COOKIE}={value}; Path=/; Max-Age={max_age if payload else 0}; HttpOnly; SameSite=Lax{secure}"

    def read_body(self, limit=8192):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ValueError("too large")
        raw = self.rfile.read(n) if n else b""
        if "json" in (self.headers.get("Content-Type") or ""):
            return json.loads(raw or b"{}")
        return {k: v[0] for k, v in parse_qs(raw.decode()).items()}

    def log_message(self, fmt, *args):  # quieter console
        if "/api/run?" in (args[0] if args else ""):
            super().log_message(fmt, *args)

    # ---------------------------------------------------------- helpers
    def send_json(self, obj, code=200, headers=()):
        body = json.dumps(obj).encode()
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, ctype):
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        if GATED and ctype.startswith("text/html"):
            secure = "; Secure" if (CANONICAL_HOST or self.headers.get("X-Forwarded-Proto") == "https") else ""
            self.send_header("Set-Cookie", f"{VISIT_COOKIE}={make_visit()}; Path=/; Max-Age={VISIT_TTL}; HttpOnly; SameSite=Strict{secure}")
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def sse(self, event, data):
        self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
        self.wfile.flush()

    # ---------------------------------------------------------- routes
    def do_GET(self):
        u = urlparse(self.path)
        if self.host_redirect() or not self.gate(u.path) or not self.api_ok(u.path):
            return
        if u.path in ("/", "/index.html"):
            # public landing page with the sign-up form; on a local run (no sign-up) go straight to the dashboard
            self.send_file(os.path.join(HERE, "landing.html" if GATED else "dashboard.html"), "text/html; charset=utf-8")
        elif u.path in ("/dashboard", "/dashboard.html"):
            self.send_file(os.path.join(HERE, "dashboard.html"), "text/html; charset=utf-8")
        elif u.path == "/admin":
            self.send_file(os.path.join(HERE, "admin.html"), "text/html; charset=utf-8")
        elif u.path == "/robots.txt":
            body = b"User-agent: *\nDisallow: /api/\nDisallow: /admin\nAllow: /\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/api/session":
            s = self.session()
            self.send_json({"signed_in": bool(s), "name": s["n"] if s else None,
                            "admin": bool(s and s.get("a")), "gated": GATED})
        elif u.path == "/api/admin/registrations":
            s = self.session()
            if not (s and s.get("a")):
                return self.send_json({"error": "admins only"}, 403)
            regs = read_registrations()
            if parse_qs(u.query).get("format", [""])[0] == "csv":
                buf = io.StringIO()
                w = csv.DictWriter(buf, fieldnames=REG_FIELDS, extrasaction="ignore")
                w.writeheader()
                w.writerows(regs)
                body = buf.getvalue().encode("utf-8-sig")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="registrations.csv"')
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return self.wfile.write(body)
            self.send_json(regs)
        elif u.path == "/api/schema":
            self.send_json({"models": SCHEMA, "backends": ["cpu", "gpu"], "gpu": GPU})
        elif u.path == "/api/runs":
            # the owner id stays on the server: it is what proves who may delete a run
            self.send_json([{k: v for k, v in r.items() if k != "owner"} | {"can_delete": self.can_delete(r.get("owner"))}
                            for r in list_runs()])
        elif u.path.startswith("/api/runs/"):
            rid = u.path.rsplit("/", 1)[-1]
            if not re.fullmatch(r"[\w\-]+", rid) or not os.path.exists(os.path.join(RUNS_DIR, rid + ".json")):
                return self.send_json({"error": "not found"}, 404)
            with open(os.path.join(RUNS_DIR, rid + ".json")) as f:
                self.send_json({k: v for k, v in json.load(f).items() if k != "owner"})
        elif u.path in ("/api/extras", "/api/transmon"):
            # model-specific figures + derived numbers for the current inputs (no simulation needed)
            q = parse_qs(u.query)
            model = "transmon" if u.path == "/api/transmon" else q.get("model", [""])[0]
            if model not in EXTRAS:
                return self.send_json({"error": "no extras for this model"}, 404)
            try:
                a = make_args(model, "cpu", q)
                self.send_json(extras(model, a))
            except Exception as e:
                self.send_json({"error": f"{type(e).__name__}: {e}"}, 400)
        elif u.path in ("/explorer", "/explorer.html"):
            self.send_file(os.path.join(HERE, "explorer.html"), "text/html; charset=utf-8")
        elif u.path in ("/chain", "/chain.html"):
            self.send_file(os.path.join(HERE, "chain.html"), "text/html; charset=utf-8")
        elif u.path in ("/api/chain100", "/api/ibm-step1"):
            name = "chain100.json" if u.path.endswith("chain100") else "step1.json"
            p = os.path.join(HERE, "data", "ibm", name)
            if not os.path.exists(p):
                return self.send_json({"error": f"data/ibm/{name} missing: run {'chain100.sh' if 'chain' in name else 'ibm_step1.sh'}"}, 404)
            self.send_file(p, "application/json")
        elif u.path in ("/molecules", "/molecules.html"):
            self.send_file(os.path.join(HERE, "molecules.html"), "text/html; charset=utf-8")
        elif u.path == "/nav.js":
            self.send_file(os.path.join(HERE, "nav.js"), "text/javascript; charset=utf-8")
        elif u.path == "/vibchart.js":
            self.send_file(os.path.join(HERE, "vibchart.js"), "text/javascript; charset=utf-8")
        elif u.path == "/api/vibrations":
            p = os.path.join(HERE, "data", "vibrations.json")
            if not os.path.exists(p):
                return self.send_json({"error": "data/vibrations.json missing: run vibrations.sh"}, 404)
            if self.member():
                return self.send_file(p, "application/json")
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            d["molecules"] = [m for m in d.get("molecules", []) if m.get("source") != "new"]   # keyed by structure
            self.send_json(d)
        elif u.path == "/api/molecules":
            p = os.path.join(HERE, "data", "new_molecules.json")
            if not os.path.exists(p):
                return self.send_json({"error": "data/new_molecules.json missing: run generate_molecules.sh"}, 404)
            if self.member():
                return self.send_file(p, "application/json")
            with open(p, encoding="utf-8") as f:
                self.send_json(locked_molecules(json.load(f)))
        elif u.path in ("/api/explorer/summary", "/api/explorer/rows", "/api/explorer/item"):
            # one screen at a time, scored on the server: there is no whole-dataset download
            q = parse_qs(u.query)
            if u.path.endswith("summary"):
                out = explorer_api.summary()
            elif u.path.endswith("rows"):
                if not self.rows_ok(explorer_api._num(q, "limit", explorer_api.PAGE_MAX, 1, explorer_api.PAGE_MAX, int)):
                    return
                out = explorer_api.query(q)
            else:
                if not self.rows_ok(1):
                    return
                out = explorer_api.item(q)
            if out is None:
                return self.send_json({"error": "data/explorer.json missing: run build_materials.sh"}, 404)
            self.send_json(out, 404 if out.get("error") else 200)
        elif u.path == "/api/run":
            self.handle_run(parse_qs(u.query))
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        if self.host_redirect(308):
            return
        if not self.same_origin():
            return self.send_json({"error": "cross-site request refused"}, 403)
        if u.path == "/api/logout":
            return self.send_json({"ok": True}, headers=[("Set-Cookie", self.cookie_header(None))])
        if not GATED:
            return self.send_json({"error": "sign-up is off on this server"}, 404)
        try:
            form = self.read_body()
        except Exception:
            return self.send_json({"error": "Could not read the form."}, 400)
        if u.path == "/api/register":
            return self.register(form)
        if u.path == "/api/admin/login":
            if not ADMIN_KEY or not rate_ok("admin:" + self.client_ip(), 10):
                return self.send_json({"error": "Not available right now."}, 429)
            if not hmac.compare_digest(str(form.get("key", "")).encode(), ADMIN_KEY.encode()):
                return self.send_json({"error": "Wrong key."}, 403)
            print("admin signed in", flush=True)
            return self.send_json({"ok": True}, headers=[("Set-Cookie", self.cookie_header({"id": "admin", "n": "Admin", "a": 1}))])
        self.send_json({"error": "not found"}, 404)

    def register(self, form):
        f = {k: str(form.get(k, "")).strip() for k in ("name", "email", "organisation", "role", "interest", "website")}
        if f["website"]:                                   # hidden field: only bots fill it in
            return self.send_json({"ok": True, "name": f["name"][:100]})
        errors = []
        if not 1 <= len(f["name"]) <= 100:
            errors.append("Please give your name.")
        if len(f["email"]) > 254 or not EMAIL_RE.fullmatch(f["email"]):
            errors.append("Please give a valid email address.")
        if len(f["organisation"]) > 150 or len(f["role"]) > 60 or len(f["interest"]) > 1500:
            errors.append("One of the answers is too long.")
        if str(form.get("consent", "")).lower() not in ("1", "true", "on", "yes"):
            errors.append("Please tick the box to agree to the privacy note.")
        if errors:
            return self.send_json({"error": " ".join(errors)}, 400)
        if not rate_ok("reg:" + self.client_ip(), 5):
            return self.send_json({"error": "Too many sign-ups from this address. Please try again in an hour."}, 429)
        rec = {"id": secrets.token_hex(8), "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "name": f["name"], "email": f["email"].lower(), "organisation": f["organisation"],
               "role": f["role"], "interest": f["interest"]}
        with RATE_LOCK:
            if os.path.exists(REG_FILE) and os.path.getsize(REG_FILE) > 20_000_000:
                return self.send_json({"error": "Sign-ups are paused. Please email us instead."}, 503)
            with open(REG_FILE, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
        print(f"sign-up {rec['time']} {rec['id']}", flush=True)
        self.send_json({"ok": True, "name": rec["name"]},
                       headers=[("Set-Cookie", self.cookie_header({"id": rec["id"], "n": rec["name"][:40], "a": 0}))])

    def do_DELETE(self):
        u = urlparse(self.path)
        if self.host_redirect(308) or not self.gate(u.path, members=True):
            return
        if not self.same_origin():
            return self.send_json({"error": "cross-site request refused"}, 403)
        rid = u.path.rsplit("/", 1)[-1] if u.path.startswith("/api/runs/") else ""
        path = os.path.join(RUNS_DIR, rid + ".json")
        if not re.fullmatch(r"[\w\-]+", rid) or not os.path.exists(path):
            return self.send_json({"error": "not found"}, 404)
        try:
            with open(path) as f:
                owner = json.load(f).get("owner")
        except Exception:
            owner = None
        if not self.can_delete(owner):
            return self.send_json({"error": "Only the person who ran it (or an admin) can delete this run."}, 403)
        os.makedirs(TRASH_DIR, exist_ok=True)
        os.replace(path, os.path.join(TRASH_DIR, rid + ".json"))
        print(f"deleted run {rid} (by {self.user() or 'local user'})", flush=True)
        self.send_json({"deleted": rid})

    def handle_run(self, q):
        model = q.get("model", ["cavity"])[0]
        backend = q.get("backend", ["cpu"])[0]
        if model not in SCHEMA or backend not in ("cpu", "gpu"):
            return self.send_json({"error": "bad model or backend"}, 400)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")  # one run per connection; ends cleanly after "done"
        self.end_headers()
        self.close_connection = True

        if not RUN_LOCK.acquire(blocking=False):
            return self.sse("error", {"message": "Another run is in progress. Stop it first."})
        record = None
        try:
            if backend == "gpu" and SCHEMA[model].get("cpu_only"):
                raise RuntimeError("The transmon model is CPU-only: it is a handful of levels, a GPU adds nothing.")
            if backend == "gpu" and not GPU:
                raise RuntimeError("No NVIDIA GPU on this machine. The GPU backend needs Colab, Brev or similar.")
            a = make_args(model, backend, q)
            params = {k: v for k, v in vars(a).items() if not k.startswith("spacer")}
            H, dims, c_ops, obs, psi0, times = sim.MODELS[model](a)
            p_title, p_labels, p_rows, p_kind, p_ops = sim.profile_for(model, a, dims)
            pace = min(max(float(q.get("pace", [0])[0]), 0), 500) / 1000  # slow-motion, seconds per point
            size = int(np.prod(list(dims.values())))
            rid = run_id(model)
            meta = {
                "id": rid, "model": model, "backend": backend, "params": params,
                "size": size, "noise_channels": len(c_ops),
                "observables": list(obs), "times": [float(t) for t in times],
                "profile": {"title": p_title, "labels": p_labels, "kind": p_kind},
            }
            meta["time_unit"] = SCHEMA[model].get("time_unit", "µs")
            if getattr(a, "spacer_name", ""):
                meta["spacer"] = a.spacer_name
            if model in EXTRAS:
                meta.update(extras(model, a))
            who = self.session()
            record = dict(meta, steps=[], status="running", created=time.time(),
                          owner=who["id"] if who else None, owner_name=who["n"] if who else None)
            self.sse("meta", meta)

            t0 = time.perf_counter()
            stream = (sim.stream_cpu(H, dims, c_ops, obs, psi0, times, p_rows) if backend == "cpu"
                      else sim.stream_gpu(H, dims, c_ops, obs, psi0, times, p_ops))
            for step in stream:
                step["elapsed"] = time.perf_counter() - t0
                record["steps"].append(step)
                self.sse("step", step)  # raises if the browser hung up -> run stops
                if pace:
                    time.sleep(pace)
            record.update(status="done", elapsed=time.perf_counter() - t0)
            self.sse("done", {"elapsed": record["elapsed"], "id": rid})
        except (BrokenPipeError, ConnectionResetError):
            if record:
                record["status"] = "stopped"
        except Exception as e:
            if record:
                record["status"] = "error"
            try:
                self.sse("error", {"message": f"{type(e).__name__}: {e}"})
            except OSError:
                pass
        finally:
            RUN_LOCK.release()
            if record and record["steps"]:
                record.setdefault("elapsed", record["steps"][-1]["elapsed"])
                with open(os.path.join(RUNS_DIR, record["id"] + ".json"), "w") as f:
                    json.dump(record, f)


# What visitors see of the generated molecules: scores and summaries, not the structures (name, SMILES,
# drawing, salt, PubChem record), so the designs are not handed out before anyone signs up.
LOCKED_DROP = ("smiles", "svg", "salt", "pubchem_cid")


def locked_molecules(d):
    out = {k: v for k, v in d.items() if k != "molecules"} | {"locked": True, "molecules": []}
    for i, m in enumerate(d.get("molecules", []), 1):
        r = {k: v for k, v in m.items() if k not in LOCKED_DROP}
        r["label"] = f"{m.get('family', 'new')} {m.get('role', 'spacer')} #{i}"
        r["id"] = f"design-{i}"
        r["known"] = bool(m.get("pubchem_cid"))
        out["molecules"].append(r)
    return out


REG_FIELDS = ["time", "name", "email", "organisation", "role", "interest", "id"]


def read_registrations():
    """All sign-ups, newest first."""
    if not os.path.exists(REG_FILE):
        return []
    out = []
    with open(REG_FILE, encoding="utf-8") as fh:
        for line in fh:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out[::-1]


def list_runs():
    out = []
    for name in sorted(os.listdir(RUNS_DIR), reverse=True):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(RUNS_DIR, name)) as f:
                r = json.load(f)
            out.append({k: r.get(k) for k in ("id", "model", "backend", "params", "size",
                                              "status", "elapsed", "created", "owner", "owner_name")}
                       | {"points": len(r.get("steps", []))})
        except Exception:
            continue
    return out[:50]


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    host = os.environ.get("HOST", "0.0.0.0")  # use HOST=127.0.0.1 on a cloud box (reach it via SSH tunnel)
    print(f"Quantum dashboard on http://localhost:{port}  (bound to {host}, GPU available: {GPU})", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
