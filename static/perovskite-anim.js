// Explorer "New to perovskites?" box: a rotating 3D ball-and-stick model that acts out each idea in the primer.
// Atoms are drawn on a canvas; Anime.js v4 (vendored /anime.esm.min.js) drives every position, fade and camera move.
// Geometry is to scale in Pb–I bond lengths (1 unit = 3.2 Å); molecules are built atom by atom (MA, PEA, BDA, water).
import { createTimeline } from "/anime.esm.min.js";

const root = document.getElementById("pvAnim");
if (root) start(root, root.closest("details"));

function start(root, box) {
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const TEXT = "#f2f2f2", INK = "#b3b3b3", MUTED = "#8a8a8a", BRAND = "#76b900", BAD = "#ff6b5e";
  const COL = { Pb: "#7d8a99", N: "#5b82ff", C: "#9a9a9a", H: "#ececec", O: "#e5483b" };
  const RAD = { Pb: .30, N: .17, C: .17, H: .10, O: .19 };
  const HALC = ["#a35fe0", "#c0503a", "#46c46a"], HALR = [.33, .30, .27];       // I, Br, Cl
  const FONT = getComputedStyle(document.body).fontFamily || "system-ui, sans-serif";

  // ---------- small helpers
  const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]], mul = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const norm = a => mul(a, 1 / (Math.hypot(...a) || 1));
  const pos = a => [a.x, a.y, a.z];
  const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
  const rnd = (a, b) => a + Math.random() * (b - a);
  const basis = (d, ph = 0) => {                       // two unit vectors at right angles to d, turned by ph
    const t = Math.abs(d[0]) < .9 ? [1, 0, 0] : [0, 1, 0];
    const u = norm(cross(d, t)), v = cross(d, u), c = Math.cos(ph), s = Math.sin(ph);
    return [add(mul(u, c), mul(v, s)), add(mul(v, c), mul(u, -s))];
  };
  const hex2 = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
  const rgb2 = c => "#" + c.map(v => Math.round(clamp(v, 0, 255)).toString(16).padStart(2, "0")).join("");
  const mix = (a, b, t) => { const A = hex2(a), B = hex2(b); return rgb2(A.map((v, i) => v + (B[i] - v) * t)); };
  const ramp = (list, k) => { const i = Math.min(list.length - 2, Math.floor(k)); return mix(list[i], list[i + 1], clamp(k - i)); };
  const lerpN = (list, k) => { const i = Math.min(list.length - 2, Math.floor(k)); return list[i] + (list[i + 1] - list[i]) * clamp(k - i); };

  // shaded sphere sprites, one per colour
  const sprites = new Map(), darker = new Map();
  function sprite(hex) {
    hex = rgb2(hex2(hex).map(v => Math.round(v / 6) * 6));
    let c = sprites.get(hex);
    if (c) return c;
    c = document.createElement("canvas"); c.width = c.height = 64;
    const x = c.getContext("2d"), g = x.createRadialGradient(23, 21, 2, 32, 32, 31);
    g.addColorStop(0, mix(hex, "#ffffff", .6)); g.addColorStop(.42, hex); g.addColorStop(1, mix(hex, "#000000", .65));
    x.fillStyle = g; x.beginPath(); x.arc(32, 32, 31, 0, 7); x.fill();
    sprites.set(hex, c);
    return c;
  }
  const dark = hex => { let d = darker.get(hex); if (!d) { d = mix(hex, "#000000", .3); darker.set(hex, d); } return d; };

  // ---------- scene model
  let S = null;
  const grp = (o = {}) => ({ x: 0, y: 0, z: 0, o: 1, ...o });
  function atom(el, p, gs = [], o = {}) { const a = { el, x: p[0], y: p[1], z: p[2], gs, o: 1, s: 1, ...o }; S.atoms.push(a); return a; }
  const bond = (a, b) => S.bonds.push([a, b, Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z)]);
  const SITES = [[-1, -1], [-1, 1], [1, -1], [1, 1]];

  // corner-sharing PbX6 network: Pb on even grid points, halide (X) between them; A sites in the cube centres
  function lattice(nx, ny, nz, gs, { off = [0, 0, 0], o = 1, fo = 0 } = {}) {
    const seen = new Map(), pbs = [], xs = [], octs = [], sites = [];
    const D = [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]];
    for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) for (let k = 0; k < nz; k++) {
      const p = add([2 * i - (nx - 1), 2 * j - (ny - 1), 2 * k - (nz - 1)], off);
      const pb = atom("Pb", p, gs, { o, cat: "Pb" + j }); pbs.push(pb);
      const nb = D.map(d => {
        const q = add(p, d), key = q.map(v => v.toFixed(2)).join(",");
        let x = seen.get(key);
        if (!x) { x = atom("X", q, gs, { o, cat: "I" }); seen.set(key, x); xs.push(x); }
        bond(pb, x);
        return x;
      });
      const f = { o: fo }; octs.push({ pb, nb, fo: f });
      for (const a of [0, 1]) for (const b of [2, 3]) for (const c of [4, 5]) S.faces.push({ v: [nb[a], nb[b], nb[c]], fo: f });
      if (i < nx - 1 && j < ny - 1 && k < nz - 1) sites.push(add(p, [1, 1, 1]));
    }
    return { pbs, xs, octs, sites };
  }

  function hydrogens(at, dirs, len, gs, o) { for (const d of dirs) bond(at, atom("H", add(pos(at), mul(norm(d), len)), gs, o)); }
  const tetra = (d, u, v, back, ph = 0) => [0, 1, 2].map(k => {
    const a = ph + k * 2.094;
    return add(mul(d, back), add(mul(u, .94 * Math.cos(a)), mul(v, .94 * Math.sin(a))));
  });

  // methylammonium CH3NH3+
  function MA(c, gs, d, o = {}) {
    d = norm(d); const [u, v] = basis(d, o.ph || 0), op = { cat: "MA", ...o };
    const C = atom("C", add(c, mul(d, -.23)), gs, op), N = atom("N", add(c, mul(d, .23)), gs, { ...op, tag: "+" });
    bond(C, N);
    hydrogens(C, tetra(d, u, v, -.33), .34, gs, op);
    hydrogens(N, tetra(d, u, v, .33, 1.047), .32, gs, op);
  }

  // phenethylammonium C6H5CH2CH2NH3+, charged NH3+ head at p0, tail pointing along d
  function PEA(p0, d, gs, o = {}) {
    d = norm(d); const [u, v] = basis(d, o.ph || 0), op = { cat: "PEA", ...o };
    const at = (el, p, x) => atom(el, p, gs, { ...op, ...x });
    const P = (a, b) => add(p0, add(mul(d, a), mul(u, b)));
    const N = at("N", p0, { tag: "+" }), C1 = at("C", P(.40, .15)), C2 = at("C", P(.80, -.15)), Ci = at("C", P(1.20, .15));
    bond(N, C1); bond(C1, C2); bond(C2, Ci);
    const rc = add(pos(Ci), mul(d, .44)), ring = [Ci];
    for (let k = 1; k < 6; k++) {
      const t = Math.PI + k * Math.PI / 3;
      const r = at("C", add(rc, add(mul(d, .44 * Math.cos(t)), mul(u, .44 * Math.sin(t)))));
      bond(ring[k - 1], r); ring.push(r);
    }
    bond(ring[5], Ci);
    if (o.noH) return;
    hydrogens(N, tetra(d, u, v, -.33), .32, gs, op);
    hydrogens(C1, [add(mul(u, -.55), mul(v, .83)), add(mul(u, -.55), mul(v, -.83))], .34, gs, op);
    hydrogens(C2, [add(mul(u, .55), mul(v, .83)), add(mul(u, .55), mul(v, -.83))], .34, gs, op);
    for (let k = 1; k < 6; k++) hydrogens(ring[k], [add(pos(ring[k]), mul(rc, -1))], .33, gs, op);
  }

  // butane-1,4-diammonium +H3N(CH2)4NH3+: a Dion–Jacobson spacer, charged at both ends
  function BDA(p0, d, gs, o = {}) {
    d = norm(d); const [u, v] = basis(d, o.ph || 0), op = { cat: "PEA", ...o };
    const chain = [atom("N", p0, gs, op)];
    for (let i = 1; i <= 4; i++) chain.push(atom("C", add(p0, add(mul(d, .40 * i), mul(u, i % 2 ? .15 : -.15))), gs, op));
    chain.push(atom("N", add(p0, mul(d, 2.0)), gs, op));
    for (let i = 1; i < chain.length; i++) bond(chain[i - 1], chain[i]);
    hydrogens(chain[0], tetra(d, u, v, -.33), .32, gs, op);
    hydrogens(chain[5], tetra(d, u, v, .33), .32, gs, op);
    for (let i = 1; i <= 4; i++) { const s = i % 2 ? -.55 : .55; hydrogens(chain[i], [add(mul(u, s), mul(v, .83)), add(mul(u, s), mul(v, -.83))], .34, gs, op); }
  }

  function H2O(gs) {
    const O = atom("O", [0, 0, 0], gs, { s: 1.8 });                       // drawn larger so it reads at this zoom
    for (const s of [1, -1]) bond(O, atom("H", [s * .44, .34, 0], gs, { s: 1.8 }));
  }

  // ---------- canvas
  const cv = document.createElement("canvas"), ctx = cv.getContext("2d");
  root.append(cv);
  let W = 720, H = 320, CX = 225, CY = 165, PX = 452, PY = 36, PW = 250, wide = true, dpr = 1, scale = 1, spin = 0;
  function layout() {
    const w = root.clientWidth;
    if (!w) return;
    wide = w >= 600;
    if (wide) { W = 720; H = 360; CX = 225; CY = 186; PX = 452; PY = 50; PW = 250; }
    else { W = 360; H = 600; CX = 180; CY = 190; PX = 22; PY = 370; PW = 316; }
    scale = w / W; dpr = window.devicePixelRatio || 1;
    cv.width = Math.round(w * dpr); cv.height = Math.round(H * scale * dpr);
    cv.style.width = w + "px"; cv.style.height = Math.round(H * scale) + "px";
    draw();
  }

  function T(x, y, s, o = {}) {
    const a = o.a ?? 1;
    if (a < .01) return;
    ctx.globalAlpha = a; ctx.fillStyle = o.c || INK; ctx.textAlign = o.al || "left"; ctx.textBaseline = "alphabetic";
    ctx.font = `${o.w || 400} ${o.s || 12}px ${FONT}`;
    ctx.fillText(s, x, y);
    ctx.globalAlpha = 1;
  }
  function rr(x, y, w, h, r) {
    ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
  }
  const colourOf = el => el === "X" ? ramp(HALC, S.hal.k) : COL[el];
  function dot(x, y, el, a = 1, r = 6) {
    if (a < .01) return;
    ctx.globalAlpha = a; ctx.drawImage(sprite(colourOf(el)), x - r, y - r, 2 * r, 2 * r); ctx.globalAlpha = 1;
  }
  // a panel line: bullet (atom or icon), heading and a muted second line
  function item(y, el, head, sub, a, icon, ic) {
    if (a < .01) return;
    if (icon) T(PX + 6, y + 5, icon, { a, c: ic, w: 700, s: 14, al: "center" }); else dot(PX + 6, y, el, a);
    T(PX + 20, y + 5, head, { a, c: TEXT, w: 600, s: 13 });
    if (sub) T(PX + 20, y + 22, sub, { a, c: MUTED, s: 11.5 });
  }

  function draw() {
    if (!S || !cv.width) return;
    ctx.setTransform(dpr * scale, 0, 0, dpr * scale, 0, 0);
    ctx.clearRect(0, 0, W, H);
    if (S.bg) S.bg();
    const c = S.cam, yaw = c.yaw + spin, cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(c.pitch), sp = Math.sin(c.pitch);
    const Z0 = 30, zoom = c.zoom * (wide ? 1 : .8), k = S.hal.k, ls = 1 - .035 * k, hr = lerpN(HALR, k), hl = S.hl;
    const proj = (x, y, z) => {
      x = x * ls - c.tx; y = y * ls - c.ty; z = z * ls - c.tz;
      const X = x * cy + z * sy, Z1 = -x * sy + z * cy, Y = y * cp - Z1 * sp, Z = y * sp + Z1 * cp, f = Z0 / (Z0 + Z);
      return [CX + X * f * zoom, CY + Y * f * zoom, Z, f];
    };
    const items = [];
    for (const a of S.atoms) {
      let x = a.x, y = a.y, z = a.z, o = a.o;
      for (const g of a.gs) { x += g.x; y += g.y; z += g.z; o *= g.o; }
      if (hl.focus > .001 && a.cat) o *= 1 - .75 * hl.focus * (1 - (hl[a.cat] || 0));
      a._o = o; a._w = [x, y, z];
      if (o < .01 || a.s < .01) { a._p = null; continue; }
      a._p = proj(x, y, z);
      items.push([a._p[2], 0, a]);
    }
    for (const b of S.bonds) if (b[0]._p && b[1]._p) items.push([(b[0]._p[2] + b[1]._p[2]) / 2 + .02, 1, b]);
    for (const f of S.faces) {
      if (f.fo.o < .01) continue;
      const [p, q, r] = f.v;
      if (p._p && q._p && r._p) items.push([(p._p[2] + q._p[2] + r._p[2]) / 3, 2, f]);
    }
    items.sort((p, q) => q[0] - p[0]);
    const hcol = ramp(HALC, k);
    ctx.lineCap = "round";
    for (const [, t, it] of items) {
      if (t === 0) {
        const a = it, [x, y, , f] = a._p;
        if (a.el === "e") { glow(x, y, a._o); continue; }
        const r = (a.el === "X" ? hr : RAD[a.el]) * f * zoom * a.s * ls;
        ctx.globalAlpha = a._o;
        ctx.drawImage(sprite(colourOf(a.el)), x - r, y - r, 2 * r, 2 * r);
        const h = hl.focus > .01 && a.cat && a.el !== "H" && a.el !== "X" ? (hl[a.cat] || 0) * hl.focus : 0;
        if (h > .02) { ctx.globalAlpha = h * .85; ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 1.1; ctx.beginPath(); ctx.arc(x, y, r + 1.6, 0, 7); ctx.stroke(); }
      } else if (t === 1) {
        const [a, b, l0] = it, pa = a._p, pb = b._p, mx = (pa[0] + pb[0]) / 2, my = (pa[1] + pb[1]) / 2;
        const stretch = Math.hypot(a._w[0] - b._w[0], a._w[1] - b._w[1], a._w[2] - b._w[2]) / l0;   // bonds only form when atoms are close
        ctx.globalAlpha = Math.min(a._o, b._o) * .95 * clamp((1.5 - stretch) / .4);
        if (ctx.globalAlpha < .01) continue;
        ctx.lineWidth = Math.max(.6, .075 * zoom * (pa[3] + pb[3]) / 2 * ls);
        ctx.strokeStyle = dark(colourOf(a.el)); ctx.beginPath(); ctx.moveTo(pa[0], pa[1]); ctx.lineTo(mx, my); ctx.stroke();
        ctx.strokeStyle = dark(colourOf(b.el)); ctx.beginPath(); ctx.moveTo(mx, my); ctx.lineTo(pb[0], pb[1]); ctx.stroke();
      } else {
        const [p, q, r] = it.v, a = it.fo.o * Math.min(p._o, q._o, r._o);
        ctx.beginPath(); ctx.moveTo(p._p[0], p._p[1]); ctx.lineTo(q._p[0], q._p[1]); ctx.lineTo(r._p[0], r._p[1]); ctx.closePath();
        ctx.globalAlpha = .2 * a; ctx.fillStyle = hcol; ctx.fill();
        ctx.globalAlpha = .4 * a; ctx.strokeStyle = hcol; ctx.lineWidth = .7; ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;
    const tagO = S.P.tag || 0;
    if (tagO > .01) for (const a of S.atoms) if (a.tag && a._p) {
      const r = (a.el === "X" ? hr : RAD[a.el]) * a._p[3] * zoom * ls;
      T(a._p[0] + r * .8 + 1, a._p[1] - r * .8, a.tag, { a: tagO * a._o, c: TEXT, s: 9.5, w: 700 });
    }
    if (S.after) S.after(proj);
    T(18, 24, `${S.n + 1} / 5`, { c: BRAND, w: 700, s: 11 });
    T(46, 24, S.title, { c: INK, w: 600, s: 12 });
    if (S.panel) S.panel();
  }
  function glow(x, y, a) {
    const g = ctx.createRadialGradient(x, y, 0, x, y, 11);
    g.addColorStop(0, "#ffffff"); g.addColorStop(.35, "#ffe27a"); g.addColorStop(1, "rgba(255,226,122,0)");
    ctx.globalAlpha = a; ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, 11, 0, 7); ctx.fill();
    T(x + 10, y - 7, "e⁻", { a, c: "#ffe27a", s: 11, w: 700 });
  }

  const end = (tl, t) => tl.add({ v: 0 }, { v: 1, duration: 1 }, t - 1);

  // ---------- 1. the ABX3 cage
  function st1(tl) {
    S.title = "The ABX₃ cage";
    const L = lattice(2, 2, 2, [], { o: 0 }), o0 = L.octs[0], pb0 = o0.pb;
    Object.assign(S.cam, { yaw: .55, pitch: -.42, zoom: 66, tx: pb0.x, ty: pb0.y, tz: pb0.z });
    for (const a of L.pbs.concat(L.xs)) a.s = 0;
    const gM = grp({ y: -7, o: 0 });
    MA([0, 0, 0], [gM], [.55, .75, .36]);
    const P = S.P = { l1: 0, l2: 0, l3: 0, f: 0 };

    tl.add(pb0, { o: [0, 1], s: [0, 1], duration: 700, ease: "outBack(1.7)" }, 200);
    o0.nb.forEach((x, i) => {
      const t = pos(x), st = add(pos(pb0), mul([t[0] - pb0.x, t[1] - pb0.y, t[2] - pb0.z], 4.5));
      Object.assign(x, { x: st[0], y: st[1], z: st[2], s: 1 });
      tl.add(x, { x: t[0], y: t[1], z: t[2], o: [0, 1], duration: 900, ease: "outCubic" }, 900 + i * 90);
    });
    tl.add(o0.fo, { o: [0, 1], duration: 800 }, 2100);
    tl.add(S.cam, { tx: 0, ty: 0, tz: 0, zoom: 40, duration: 1700, ease: "inOutCubic" }, 3100);
    const rest = L.pbs.concat(L.xs).filter(a => a !== pb0 && !o0.nb.includes(a));
    const dist = a => Math.hypot(a.x - pb0.x, a.y - pb0.y, a.z - pb0.z);
    tl.add(rest, { o: [0, 1], s: [0, 1], duration: 550, ease: "outBack(1.6)", delay: a => dist(a) * 170 }, 3500);
    tl.add(L.octs.slice(1).map(o => o.fo), { o: [0, 1], duration: 800 }, 4800);
    tl.add(gM, { y: 0, o: [0, 1], duration: 1300, ease: "outCubic" }, 5700);
    tl.add(P, { l1: 1, duration: 500 }, 700);
    tl.add(P, { l2: 1, duration: 500 }, 1900);
    tl.add(P, { l3: 1, duration: 500 }, 6100);
    tl.add(P, { f: 1, duration: 600 }, 7100);
    end(tl, 10500);

    S.panel = () => {
      item(PY + 14, "Pb", "B = Pb²⁺ · lead", "the centre of each cage", P.l1);
      item(PY + 66, "X", "X = I⁻ · iodide", "6 per lead make an octahedron", P.l2);
      item(PY + 118, "N", "A = MA⁺ · methylammonium", "CH₃NH₃⁺, sits in the gap", P.l3);
      T(PX, PY + 196, "MAPbI₃", { a: P.f, c: TEXT, w: 700, s: 26 });
      T(PX, PY + 220, "one A, one B and three X", { a: P.f, c: MUTED, s: 12 });
    };
  }

  // ---------- 2. salts dry into a crystal; the halide sets the colour
  function st2(tl) {
    S.title = "Salts → crystal";
    Object.assign(S.cam, { yaw: .5, pitch: -.45, zoom: 31 });
    const L = lattice(3, 2, 3, [], { o: 0 });
    L.pbs.forEach(a => a.tag = "2+"); L.xs.forEach(a => a.tag = "−");
    const R = () => [rnd(-4.6, 4.6), rnd(-3.2, 3.2), rnd(-3.2, 3.2)];
    const ions = L.pbs.concat(L.xs);
    ions.forEach(a => { a.t = pos(a); [a.x, a.y, a.z] = R(); });
    const mols = L.sites.map((c, i) => {
      const g = grp({ o: 0 }), r = R();
      Object.assign(g, { x: r[0] - c[0], y: r[1] - c[1], z: r[2] - c[2] }); g.c = c;
      MA(c, [g], [rnd(-1, 1), rnd(-1, 1), rnd(.2, 1)], { ph: i });
      return g;
    });
    const P = S.P = { a: 0, b: 0, sol: 1, spec: 0, tag: 1 };

    tl.add(ions, { o: [0, 1], duration: 600 }, 100);
    tl.add(mols, { o: [0, 1], duration: 600 }, 100);
    for (const a of ions) {
      const p1 = R(), p2 = R();
      tl.add(a, { x: [{ to: p1[0], duration: 1100 }, { to: p2[0], duration: 1100 }], y: [{ to: p1[1], duration: 1100 }, { to: p2[1], duration: 1100 }],
        z: [{ to: p1[2], duration: 1100 }, { to: p2[2], duration: 1100 }], ease: "inOutSine" }, 300);
      tl.add(a, { x: a.t[0], y: a.t[1], z: a.t[2], duration: 1500, ease: "inOutCubic" }, 2700 + rnd(0, 400));
    }
    for (const g of mols) {
      const p1 = R(), c = g.c;
      tl.add(g, { x: p1[0] - c[0], y: p1[1] - c[1], z: p1[2] - c[2], duration: 2200, ease: "inOutSine" }, 300);
      tl.add(g, { x: 0, y: 0, z: 0, duration: 1500, ease: "inOutCubic" }, 2700 + rnd(0, 400));
    }
    tl.add(P, { a: 1, duration: 500 }, 300);
    tl.add(P, { a: 0, duration: 400 }, 2500);
    tl.add(P, { b: 1, tag: 0, duration: 600 }, 2900);
    tl.add(P, { sol: 0, duration: 1600 }, 2700);
    tl.add(L.octs.map(o => o.fo), { o: [0, 1], duration: 900 }, 4300);
    tl.add(P, { spec: 1, duration: 600 }, 4900);
    tl.add(S.hal, { k: 1, duration: 1000, ease: "inOutSine" }, 6700);
    tl.add(S.hal, { k: 2, duration: 1000, ease: "inOutSine" }, 8600);
    end(tl, 11000);

    S.bg = () => {
      if (P.sol < .01) return;
      ctx.globalAlpha = .09 * P.sol; ctx.fillStyle = "#4aa3ff"; rr(CX - 175, CY - 122, 350, 244, 18); ctx.fill();
      ctx.globalAlpha = 1;
      T(CX - 162, CY + 110, "solution", { a: .8 * P.sol, c: "#7fb8ff", s: 11 });
    };
    S.panel = () => {
      item(PY + 14, "N", "In solution", "MA⁺, I⁻ and Pb²⁺ ions drift freely", P.a);
      item(PY + 14, "N", "As it dries, + and − attract", "and the ions lock into a crystal", P.b);
      const a = P.spec, k = S.hal.k;
      if (a < .01) return;
      const y0 = PY + 78, bx = PX, by = y0 + 12, bw = PW, bh = 14;
      T(PX, y0, "The halide sets the colours it absorbs", { a, c: TEXT, w: 600, s: 13 });
      const g = ctx.createLinearGradient(bx, 0, bx + bw, 0);
      [["#6a2bd8", 0], ["#3d5cff", .15], ["#00a0ff", .27], ["#00d26a", .40], ["#c8e000", .52], ["#ffd400", .58],
       ["#ff8c00", .68], ["#ff2a00", .80], ["#a00000", 1]].forEach(([c, s]) => g.addColorStop(s, c));
      ctx.globalAlpha = a; ctx.fillStyle = g; ctx.fillRect(bx, by, bw, bh);
      const ex = bx + clamp((lerpN([775, 539, 413], k) - 380) / 400) * bw;
      ctx.globalAlpha = .74 * a; ctx.fillStyle = "#000"; ctx.fillRect(bx, by, ex - bx, bh);
      ctx.globalAlpha = a; ctx.strokeStyle = TEXT; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.moveTo(ex, by - 3); ctx.lineTo(ex, by + bh + 3); ctx.stroke();
      T(bx, by + 28, "400 nm", { a, c: MUTED, s: 10 });
      T(bx + bw / 2, by + 28, "dark = absorbed", { a, c: MUTED, s: 10, al: "center" });
      T(bx + bw, by + 28, "780 nm", { a, c: MUTED, s: 10, al: "right" });
      const sy = by + 44;
      ctx.globalAlpha = a; ctx.fillStyle = ramp(["#17100d", "#d9772b", "#efece2"], k); rr(PX, sy, 44, 44, 4); ctx.fill();
      ctx.strokeStyle = "#3a3a3a"; ctx.lineWidth = 1; ctx.stroke();
      T(PX + 22, sy + 58, "film", { a, c: MUTED, s: 10, al: "center" });
      [["Iodide · MAPbI₃ · ≈ 1.6 eV", "absorbs all visible light: black"],
       ["Bromide · MAPbBr₃ · ≈ 2.3 eV", "absorbs blue and green: orange"],
       ["Chloride · MAPbCl₃ · ≈ 3.0 eV", "almost no visible light: clear"]].forEach(([h, s], i) => {
        const w = a * clamp(1 - Math.abs(k - i) * 1.6);
        T(PX + 56, sy + 18, h, { a: w, c: TEXT, w: 600, s: 12.5 });
        T(PX + 56, sy + 36, s, { a: w, c: MUTED, s: 11.5 });
      });
      T(PX, sy + 86, "Smaller halides shrink the crystal too", { a: a * clamp(k), c: MUTED, s: 11.5 });
    };
  }

  // ---------- 3. big spacers slice the crystal into sheets
  function st3(tl) {
    S.title = "Spacers slice it into sheets";
    Object.assign(S.cam, { yaw: .55, pitch: -.3, zoom: 27 });
    const gA = grp({ o: 0 }), gB = grp({ o: 0 }), gM = grp({ o: 0 });
    const A = lattice(3, 2, 3, [gA], { off: [0, -2, 0], fo: .85 }), B = lattice(3, 2, 3, [gB], { off: [0, 2, 0], fo: .85 });
    A.sites.forEach((c, i) => MA(c, [gA], [1, .3, .2], { ph: i }));
    B.sites.forEach((c, i) => MA(c, [gB], [.2, .3, 1], { ph: i }));
    SITES.forEach(([x, z], i) => MA([x, 0, z], [gM], [.5, 1, .3], { ph: i }));
    const fT = grp({ x: 10, o: 0 }), fM1 = grp({ x: 10, o: 0 }), fM2 = grp({ x: -10, o: 0 }), fB = grp({ x: -10, o: 0 });
    SITES.forEach(([x, z], i) => {
      PEA([x, -4.25, z], [0, -1, 0], [gA, fT], { ph: i * 1.3, noH: true });
      PEA([x, .25, z], [0, 1, 0], [gA, fM1], { ph: i * 1.3 + .6, noH: true });
      PEA([x, -.25, z], [0, -1, 0], [gB, fM2], { ph: i * 1.3 + .3, noH: true });
      PEA([x, 4.25, z], [0, 1, 0], [gB, fB], { ph: i * 1.3 + .9, noH: true });
    });
    const gI = grp({ x: 11, z: 1, o: 0 });
    PEA([0, 0, 0], [1, 0, 0], [gI], { ph: .4 });
    const water = [[-1.5, -.5], [.5, 1.5], [1.8, -1.2], [-.6, 1.9]].map(([x, z]) => { const g = grp({ x, z, y: -15, o: 0 }); H2O([g]); return g; });
    const e = atom("e", [0, 2, 1], [gB], { o: 0 });
    const P = S.P = { a: 0, b: 0, c: 0, d: 0 }, ring = { r: 0, o: 0 };

    tl.add([gA, gB, gM], { o: [0, 1], duration: 700 }, 0);
    tl.add(gI, { o: [0, 1], duration: 400 }, 900);
    tl.add(gI, { x: [{ to: 3.9, duration: 900, ease: "outCubic" }, { to: 5.2, duration: 220, ease: "outQuad" }, { to: 4.1, duration: 200 },
      { to: 4.9, duration: 200 }, { to: 4.3, duration: 220 }] }, 900);
    tl.add(P, { a: 1, duration: 500 }, 1500);
    tl.add(gI, { o: 0, duration: 500 }, 3100);
    tl.add(gM, { o: 0, duration: 600 }, 3200);
    tl.add(gA, { y: -2.6, duration: 1100, ease: "inOutCubic" }, 3300);
    tl.add(gB, { y: 2.6, duration: 1100, ease: "inOutCubic" }, 3300);
    tl.add(S.cam, { zoom: 14, pitch: -.2, duration: 1300, ease: "inOutCubic" }, 3300);
    tl.add([fT, fM1, fM2, fB], { x: 0, o: [0, 1], duration: 1000, ease: "outCubic", delay: (_, i) => i * 160 }, 4100);
    tl.add(P, { b: 1, duration: 500 }, 4900);
    water.forEach((g, i) => tl.add(g, {
      o: [{ to: 1, duration: 200 }, { to: 1, duration: 900 }, { to: 0, duration: 400 }],
      y: [{ to: -10.1, duration: 800, ease: "inQuad" }, { to: -12.8, duration: 700, ease: "outQuad" }],
      x: { to: g.x + (i % 2 ? 1.2 : -1.2), duration: 1500 } }, 6000 + i * 220));
    tl.add(P, { c: 1, duration: 500 }, 6500);
    tl.add(e, { o: [0, 1], duration: 300 }, 7900);
    tl.add(e, { y: [{ to: .2, duration: 800, ease: "inQuad" }, { to: .9, duration: 250, ease: "outQuad" }, { to: .25, duration: 250, ease: "inQuad" },
      { to: .7, duration: 250 }] }, 8000);
    tl.add(ring, { r: [4, 22], o: [1, 0], duration: 700, ease: "outQuad" }, 8800);
    tl.add(ring, { r: [4, 22], o: [1, 0], duration: 700, ease: "outQuad" }, 9300);
    tl.add(P, { d: 1, duration: 500 }, 8800);
    end(tl, 11400);

    S.after = () => {
      if (e._p && ring.o > .01) { ctx.globalAlpha = ring.o; ctx.strokeStyle = BAD; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(e._p[0], e._p[1], ring.r, 0, 7); ctx.stroke(); ctx.globalAlpha = 1; }
    };
    S.panel = () => {
      item(PY + 14, "C", "Big cations don't fit the gaps", "so they slice the crystal apart", P.a);
      item(PY + 70, "Pb", "Like a club sandwich", "[spacer] [sheet × n] [spacer] …", P.b);
      T(PX + 20, PY + 109, "here n = 2 layers per sheet", { a: P.b, c: MUTED, s: 11.5 });
      item(PY + 148, null, "Spacers repel water", "so the film is more stable", P.c, "✓", BRAND);
      item(PY + 200, null, "…but they block charge", "so the cell is less efficient", P.d, "✕", BAD);
    };
  }

  // ---------- 4. reading (PEA)2MA2Pb3I10
  function st4(tl) {
    S.title = "Reading a formula";
    Object.assign(S.cam, { yaw: .6, pitch: -.28, zoom: 22 });
    const g = grp({ o: 0 }), L = lattice(3, 3, 3, [g], { fo: .8 });
    L.sites.forEach((c, i) => MA(c, [g], [1, .4, .6], { ph: i }));
    SITES.forEach(([x, z], i) => { PEA([x, -3.25, z], [0, -1, 0], [g], { ph: i * 1.3 }); PEA([x, 3.25, z], [0, 1, 0], [g], { ph: i * 1.3 + .7 }); });
    S.hl = { focus: 0, PEA: 0, MA: 0, Pb0: 0, Pb1: 0, Pb2: 0, I: 0 };
    const P = S.P = { f: 0, p0: 0, p1: 0, p2: 0, p3: 0, l0: 0, l1: 0, l2: 0, l3: 0 };

    tl.add(g, { o: [0, 1], duration: 800 }, 0);
    tl.add(P, { f: 1, duration: 600 }, 1000);
    tl.add(S.hl, { focus: 1, PEA: 1, duration: 600 }, 2000);
    tl.add(P, { p0: 1, l0: 1, duration: 500 }, 2000);
    tl.add(S.hl, { PEA: 0, MA: 1, duration: 600 }, 3700);
    tl.add(P, { p0: 0, p1: 1, l1: 1, duration: 500 }, 3700);
    tl.add(S.hl, { MA: 0, Pb0: 1, duration: 400 }, 5400);
    tl.add(S.hl, { Pb1: 1, duration: 400 }, 5900);
    tl.add(S.hl, { Pb2: 1, duration: 400 }, 6400);
    tl.add(P, { p1: 0, p2: 1, l2: 1, duration: 500 }, 5400);
    tl.add(S.hl, { Pb0: 0, Pb1: 0, Pb2: 0, I: 1, duration: 600 }, 7700);
    tl.add(P, { p2: 0, p3: 1, l3: 1, duration: 500 }, 7700);
    tl.add(S.hl, { I: 0, focus: 0, duration: 700 }, 9500);
    tl.add(P, { p3: 0, duration: 500 }, 9500);
    end(tl, 11200);

    S.panel = () => {
      if (P.f < .01) return;
      ctx.font = `700 26px ${FONT}`;
      let x = PX;
      [["(PEA)₂", P.p0], ["MA₂", P.p1], ["Pb₃", P.p2], ["I₁₀", P.p3]].forEach(([s, h]) => {
        const w = ctx.measureText(s).width;
        T(x, PY + 22, s, { a: P.f, c: mix(MUTED, "#ffffff", h), w: 700, s: 26 });
        if (h > .01) { ctx.globalAlpha = h; ctx.fillStyle = BRAND; ctx.fillRect(x, PY + 29, w, 2); ctx.globalAlpha = 1; }
        x += w + 1;
      });
      T(PX, PY + 48, "counts per formula unit", { a: P.f, c: MUTED, s: 11.5 });
      item(PY + 78, "C", "(PEA)₂ · 2 spacers", "one on each face of the sheet", P.l0);
      item(PY + 122, "N", "MA₂ · 2 methylammonium", "in the gaps inside the sheet", P.l1);
      item(PY + 166, "Pb", "Pb₃ · 3 lead", "3 layers, so the sheet is n = 3", P.l2);
      item(PY + 210, "X", "I₁₀ · 10 iodide", "3n + 1 = 10 when n = 3", P.l3);
    };
  }

  // ---------- 5. RP (one charged end, pairs with a gap) vs DJ (two charged ends, one molecule bridges)
  function st5(tl) {
    S.title = "RP vs DJ spacers";
    Object.assign(S.cam, { yaw: .6, pitch: -.22, zoom: 21 });
    const gU = grp({ y: -3.75, o: 0 }), gL = grp({ y: 3.75, o: 0 }), fRP = grp(), fDJ = grp({ o: 0 });
    lattice(3, 1, 3, [gU], { fo: .8 }); lattice(3, 1, 3, [gL], { fo: .8 });
    SITES.forEach(([x, z], i) => {
      PEA([x, 1.25, z], [0, 1, 0], [gU, fRP], { ph: i * 1.3 });
      PEA([x, -1.25, z], [0, -1, 0], [gL, fRP], { ph: i * 1.3 + .7 });
      BDA([x, -1, z], [0, 1, 0], [fDJ], { ph: i * 1.3 });
    });
    const P = S.P = { rp: 0, gap: 0, dj: 0, key: 0 };

    tl.add([gU, gL], { o: [0, 1], duration: 800 }, 0);
    tl.add(P, { rp: 1, duration: 500 }, 900);
    tl.add(P, { gap: 1, duration: 500 }, 2000);
    tl.add(P, { key: 1, duration: 500 }, 2600);
    tl.add(P, { gap: 0, duration: 400 }, 4700);
    tl.add(fRP, { o: 0, duration: 900 }, 5000);
    tl.add(gU, { y: -2.25, duration: 1500, ease: "inOutCubic" }, 5300);
    tl.add(gL, { y: 2.25, duration: 1500, ease: "inOutCubic" }, 5300);
    tl.add(fDJ, { o: 1, duration: 900 }, 6100);
    tl.add(P, { dj: 1, duration: 500 }, 6100);
    end(tl, 10200);

    S.after = proj => {
      if (P.gap < .01) return;
      const [x, y] = proj(0, 0, 0);
      T(x + 84, y + 4, "← gap", { a: P.gap, c: TEXT, w: 600, s: 12 });
    };
    S.panel = () => {
      item(PY + 14, "N", "RP · one charged end", "spacers pair up tail to tail,", P.rp);
      T(PX + 20, PY + 53, "leaving a gap between them", { a: P.rp, c: MUTED, s: 11.5 });
      item(PY + 94, "N", "DJ · two charged ends", "one molecule bridges both sheets:", P.dj);
      T(PX + 20, PY + 133, "no gap, so the sheets sit closer", { a: P.dj, c: MUTED, s: 11.5 });
      item(PY + 190, "N", "Blue = nitrogen", "the charged NH₃⁺ end of a spacer", P.key);
    };
  }

  // ---------- player
  const STAGES = [st1, st2, st3, st4, st5], CARD = [0, 1, 2, 3, 3];
  const LABELS = [
    "Step 1: a lead atom gathers six iodides into an octahedron; octahedra share corners to build the cage, and a methylammonium ion drops into the gap.",
    "Step 2: ions drift in solution, then lock into the crystal as it dries; switching iodide for bromide and chloride changes the colours absorbed.",
    "Step 3: a big spacer molecule is too large for the gaps, so the crystal splits into two-layer sheets with spacer layers between; water bounces off, charge is blocked.",
    "Step 4: the formula (PEA)2MA2Pb3I10 read off the model: 2 PEA spacers, 2 MA, 3 lead layers and 10 iodides.",
    "Step 5: RP spacers pair up with a gap; DJ spacers bridge the sheets with one molecule, so the sheets sit closer.",
  ];
  const steps = [...document.querySelectorAll("[data-pv-step]")], cards = [...document.querySelectorAll("[data-pv-card]")];
  const pauseBtn = document.getElementById("pvPause");
  let cur = 0, tl = null, paused = false, visible = false, raf = 0, last = 0;

  const fill = t => { if (steps[cur]) steps[cur].style.setProperty("--p", Math.min(1, t.currentTime / t.duration)); };
  function go(n) {
    if (tl) tl.pause();
    cur = n;
    S = { atoms: [], bonds: [], faces: [], cam: { yaw: .6, pitch: -.38, zoom: 30, tx: 0, ty: 0, tz: 0 }, hal: { k: 0 }, hl: { focus: 0 }, P: {}, n };
    tl = createTimeline({ autoplay: false, onUpdate: fill, onComplete: () => { if (!still) go((cur + 1) % STAGES.length); } });
    STAGES[n](tl);
    steps.forEach((b, i) => { b.classList.toggle("on", i === n); b.setAttribute("aria-pressed", i === n); b.style.setProperty("--p", 0); });
    cards.forEach((c, i) => c.classList.toggle("on", i === CARD[n]));
    root.setAttribute("aria-label", LABELS[n]);
    if (still) { tl.seek(tl.duration); fill(tl); }
    draw();
    sync();
  }
  const running = () => !still && !paused && visible && (!box || box.open);
  function sync() {
    if (!tl) return;
    if (running()) { tl.play(); if (!raf) { last = 0; raf = requestAnimationFrame(loop); } } else tl.pause();
  }
  function loop(ts) {
    raf = 0;
    if (!running()) return;
    const dt = last ? Math.min(.05, (ts - last) / 1000) : 0;
    last = ts; spin += dt * .22;
    draw();
    raf = requestAnimationFrame(loop);
  }

  steps.forEach((b, i) => b.addEventListener("click", () => { paused = false; setPause(); go(i); }));
  function setPause() {
    if (!pauseBtn) return;
    pauseBtn.textContent = paused ? "Play" : "Pause";
    pauseBtn.setAttribute("aria-pressed", paused);
  }
  if (pauseBtn) {
    if (still) pauseBtn.hidden = true;
    pauseBtn.addEventListener("click", () => { paused = !paused; setPause(); sync(); });
  }
  new ResizeObserver(layout).observe(root);
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; sync(); }).observe(root);
  if (box) box.addEventListener("toggle", () => { layout(); sync(); });
  layout();
  go(0);
}
