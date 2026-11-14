// Home page "What's inside" filler: a 5-qubit QAOA circuit runs, each measurement flies into a histogram of
// plans, and the cheapest plan comes out on top. Illustration only (random numbers, not a live run).
// Built with Anime.js v4 (MIT, vendored as /anime.esm.min.js). Still frame if reduced motion is on.
import { createTimeline, animate, svg as asvg, utils } from "/anime.esm.min.js";

const root = document.getElementById("circuitAnim");
if (root) {
  const NS = "http://www.w3.org/2000/svg";
  const BRAND = "#76b900", LINE = "#3a3a3a", INK = "#b3b3b3", MUTED = "#8a8a8a", BOX = "#1c1c1c";
  const el = (tag, a = {}, text) => {
    const e = document.createElementNS(NS, tag);
    for (const k in a) e.setAttribute(k, a[k]);
    if (text != null) e.textContent = text;
    return e;
  };
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // layout (viewBox units)
  const Q = 5, WY = i => 26 + i * 34, X0 = 40, XM = 400, XB = 438;
  const BARS = 8, BX0 = 520, BW = 30, BG = 6, BASE = 176, BMAX = 132;

  const s = el("svg", { viewBox: "0 0 820 196", preserveAspectRatio: "xMidYMid meet", class: "ca" });
  root.append(s);

  // wires and |0> labels
  const wires = [];
  for (let i = 0; i < Q; i++) {
    s.append(el("text", { x: 4, y: WY(i) + 4, fill: MUTED, "font-size": 12 }, "|0⟩"));
    const w = el("line", { x1: X0 - 6, y1: WY(i), x2: XB - 12, y2: WY(i), stroke: "#333", "stroke-width": 1.5 });
    s.append(w); wires.push(w);
  }

  // gates: [x, kind, qubits]
  const G = [];
  for (let i = 0; i < Q; i++) G.push([72, "H", [i]]);
  const cxLayer = (x1, x2) => { G.push([x1, "CX", [0, 1]], [x1, "CX", [2, 3]], [x2, "CX", [1, 2]], [x2, "CX", [3, 4]]); };
  cxLayer(118, 154);
  for (let i = 0; i < Q; i++) G.push([196, "Rz", [i]]);
  cxLayer(238, 274);
  for (let i = 0; i < Q; i++) G.push([316, "Rx", [i]]);
  for (let i = 0; i < Q; i++) G.push([XM - 12, "M", [i]]);

  const gates = G.map(([x, kind, q]) => {
    const g = el("g", { opacity: 0 });
    let frame;
    if (kind === "CX") {
      const [c, t] = q;
      g.append(el("line", { x1: x, y1: WY(c), x2: x, y2: WY(t) + 8, stroke: LINE, "stroke-width": 1.5 }));
      g.append(el("circle", { cx: x, cy: WY(c), r: 3.5, fill: INK }));
      frame = el("circle", { cx: x, cy: WY(t), r: 8, fill: BOX, stroke: LINE, "stroke-width": 1.5 });
      g.append(frame, el("path", { d: `M${x - 5} ${WY(t)}h10M${x} ${WY(t) - 5}v10`, stroke: INK, "stroke-width": 1.5 }));
    } else {
      const y = WY(q[0]);
      frame = el("rect", { x: x - 11, y: y - 11, width: 22, height: 22, rx: 2, fill: BOX, stroke: LINE, "stroke-width": 1.5 });
      g.append(frame);
      if (kind === "M") {
        g.append(el("path", { d: `M${x - 6} ${y + 4}a6 6 0 0 1 12 0M${x} ${y + 4}l4 -7`, fill: "none", stroke: INK, "stroke-width": 1.3 }));
      } else {
        g.append(el("text", { x, y: y + 4, "text-anchor": "middle", fill: INK, "font-size": kind === "H" ? 12 : 10, "font-weight": 700 }, kind));
      }
    }
    s.append(g);
    return { g, frame, x };
  });

  // measured bits, one per wire
  const bits = [];
  for (let i = 0; i < Q; i++) {
    const t = el("text", { x: XB, y: WY(i) + 4, fill: BRAND, "font-size": 13, "font-weight": 700, opacity: 0 }, "0");
    s.append(t); bits.push(t);
  }

  // histogram of plans
  s.append(el("text", { x: BX0, y: 14, fill: MUTED, "font-size": 11, "letter-spacing": ".08em" }, "PLANS SAMPLED"));
  const shots = el("text", { x: BX0 + BARS * (BW + BG) - BG, y: 14, fill: INK, "font-size": 11, "text-anchor": "end" }, "0 shots");
  s.append(shots);
  s.append(el("line", { x1: BX0 - 4, y1: BASE + .75, x2: BX0 + BARS * (BW + BG) - BG + 4, y2: BASE + .75, stroke: LINE, "stroke-width": 1.5 }));
  const bars = [];
  for (let b = 0; b < BARS; b++) {
    const r = el("rect", { x: BX0 + b * (BW + BG), y: BASE, width: BW, height: 0, rx: 3, fill: "#4a4a4a" });
    s.append(r); bars.push(r);
  }
  const bestTag = el("text", { "text-anchor": "middle", fill: BRAND, "font-size": 11, "font-weight": 700, opacity: 0 }, "best plan");
  s.append(bestTag);

  // pulses that travel along the wires
  const pulses = [];
  for (let i = 0; i < Q; i++) {
    const p = el("circle", { cx: X0, cy: WY(i), r: 3.5, fill: BRAND, opacity: 0, class: "ca-glow" });
    s.append(p); pulses.push(p);
  }
  const fx = el("g"); s.append(fx);

  // one cycle's numbers: shallow QAOA tilts the odds towards the cheap plans, the cheapest most of all
  function draw() {
    const best = utils.random(0, BARS - 1);
    const w = Array.from({ length: BARS }, (_, b) => b === best ? 1 : utils.random(15, 55) / 100);
    const sum = w.reduce((a, v) => a + v, 0);
    return { best, p: w.map(v => v / sum) };
  }
  const pick = p => { let u = Math.random(), b = 0; while (b < p.length - 1 && (u -= p[b]) > 0) b++; return b; };

  if (still) {                                   // static end state
    const { best, p } = draw(), m = Math.max(...p);
    gates.forEach(o => o.g.setAttribute("opacity", 1));
    bits.forEach(t => { t.textContent = Math.random() < .5 ? "0" : "1"; t.setAttribute("opacity", 1); });
    bars.forEach((r, b) => { const h = p[b] / m * BMAX; r.setAttribute("height", h); r.setAttribute("y", BASE - h); if (b === best) r.setAttribute("fill", BRAND); });
    bestTag.setAttribute("x", BX0 + best * (BW + BG) + BW / 2); bestTag.setAttribute("y", BASE - BMAX - 8); bestTag.setAttribute("opacity", 1);
    shots.textContent = "2,000 shots";
  } else {
    const drawWires = asvg.createDrawable(wires);
    let tl = null, onScreen = true;

    function cycle() {
      const { best, p } = draw();
      const N = 34, counts = new Array(BARS).fill(0);
      const peak = Math.max(...p) * N * 1.05;            // expected tallest bar sets the scale
      fx.replaceChildren();
      utils.set(drawWires, { draw: "0 0" });
      utils.set(bars, { height: 0, y: BASE, fill: "#4a4a4a", opacity: 1 });
      utils.set(wires, { opacity: 1 });
      utils.set([...gates.map(o => o.g), ...bits, bestTag], { opacity: 0 });
      shots.textContent = "0 shots";
      const shot = { n: 0 };

      tl = createTimeline({ autoplay: onScreen, onComplete: () => cycle() });
      tl.add(drawWires, { draw: "0 1", duration: 700, ease: "inOutQuad", delay: (_, i) => i * 70 }, 0);
      gates.forEach((o, k) => tl.add(o.g, { opacity: [0, 1], duration: 300, ease: "outQuad" }, 250 + o.x * 1.6 + (k % 5) * 12));

      // pulses sweep the circuit; each gate lights up as its pulse passes
      const T0 = 1300, TD = 1500, at = x => T0 + (x - X0) / (XM - X0) * TD;
      tl.add(pulses, { opacity: [{ to: 1, duration: 150 }, { to: 1, duration: TD - 300 }, { to: 0, duration: 150 }],
        cx: [X0, XM], duration: TD, ease: "linear" }, T0);
      gates.forEach(o => tl.add(o.frame, { stroke: [BRAND, LINE], duration: 600, ease: "outQuad" }, at(o.x) - 60));

      // measurements: bits flicker in, then shots fly into the histogram
      const TM = T0 + TD;
      tl.add(bits, { opacity: [0, 1], duration: 200, delay: (_, i) => i * 40 }, TM);
      for (let k = 0; k < N; k++) {
        const b = pick(p), t = TM + 250 + k * 85, wire = k % Q;
        const dot = el("circle", { cx: XB + 8, cy: WY(wire), r: 3, fill: b === best ? BRAND : INK, opacity: 0 });
        fx.append(dot);
        tl.call(() => bits.forEach(x => { x.textContent = Math.random() < .5 ? "0" : "1"; }), t);
        tl.add(dot, {
          opacity: [{ to: 1, duration: 60 }, { to: 1, duration: 300 }, { to: 0, duration: 120 }],
          cx: BX0 + b * (BW + BG) + BW / 2, cy: BASE - 6, duration: 480, ease: "inQuad",
          onComplete: () => {
            counts[b]++;
            const h = Math.min(BMAX, counts[b] / peak * BMAX);
            animate(bars[b], { height: h, y: BASE - h, duration: 260, ease: "outBack(1.4)" });
          },
        }, t);
      }
      const TS = TM + 250, TE = TM + 250 + N * 85 + 480;
      tl.add(shot, { n: 2000, duration: TE - TS, ease: "linear", modifier: utils.round(0),
        onUpdate: () => { shots.textContent = shot.n.toLocaleString("en-AU") + " shots"; } }, TS);

      // the cheapest plan stands out
      tl.call(() => {
        const hb = Math.min(BMAX, counts[best] / peak * BMAX);
        bestTag.setAttribute("x", BX0 + best * (BW + BG) + BW / 2);
        bestTag.setAttribute("y", BASE - Math.max(hb, 10) - 8);
      }, TE + 150);
      tl.add(bars[best], { fill: ["#4a4a4a", BRAND], duration: 400 }, TE + 150);
      tl.add(bestTag, { opacity: [0, 1], duration: 300 }, TE + 250);

      // hold, then fade and start again with new numbers
      tl.add([...gates.map(o => o.g), ...bits, ...bars, bestTag, ...wires], { opacity: 0, duration: 600, ease: "inQuad" }, TE + 2600);
    }
    cycle();

    // pause while scrolled out of view
    new IntersectionObserver(([e]) => {
      onScreen = e.isIntersecting;
      if (tl) onScreen ? tl.play() : tl.pause();
    }).observe(root);
  }
}
