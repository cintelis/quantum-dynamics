// Vibration spectrum vs the film's energy steps (shared by /molecules and /explorer).
// Data: /api/vibrations (materials/vibrations.py, GFN2-xTB). Stick height = IR intensity (relative);
// green = vibration mostly on the NH3+ head group (couples most to the lead-halide layer).
const VIB = { data: null, bySmiles: new Map(), loading: null };
const VIB_COLORS = { head: "#6aa800", rest: "#6f6f6f" };
const VIB_MAX_MEV = 450;

function vibLoad() {
  if (!VIB.loading) VIB.loading = fetch("/api/vibrations").then(r => r.ok ? r.json() : null).then(d => {
    VIB.data = d;
    if (d) for (const m of d.molecules) VIB.bySmiles.set(m.smiles, m);
    return d;
  }).catch(() => null);
  return VIB.loading;
}

function vibNS(tag, attrs = {}, text) {
  const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (text != null) e.textContent = text;
  return e;
}

// Returns a DOM section, or null when this molecule has no vibration data.
function vibSection(smiles, tip) {
  const m = VIB.bySmiles.get(smiles);
  if (!m) return null;
  const box = document.createElement("div");
  box.className = "vib";
  const h = document.createElement("div"); h.className = "sec"; h.textContent = "Vibrations vs film energy steps";
  box.append(h);
  if (m.error) { const p = document.createElement("p"); p.className = "muted"; p.textContent = "Calculation failed: " + m.error; box.append(p); return box; }
  const ns = m.matches.length;
  const w = VIB.data.window_meV, fmt = xs => xs.map(s => s.step_meV).join(", ").replace(/, ([^,]*)$/, " and $1");
  const headNear = m.matches.filter(s => s.best_head_share >= 0.2), none = m.matches.filter(s => !s.n_modes);
  const lead = document.createElement("p"); lead.className = "vib-lead";
  lead.textContent = (headNear.length ? `NH₃⁺ head-group vibrations sit within ±${w} meV of the ${fmt(headNear)} meV step${headNear.length > 1 ? "s" : ""}. ` : `No head-group vibration within ±${w} meV of any step. `) +
    (none.length ? `Nothing near ${fmt(none)} meV: ${none.length > 1 ? "those steps fall" : "that step falls"} in the gap where organic molecules barely vibrate, so no spacer vibration can bridge ${none.length > 1 ? "them" : "it"} directly.` : "");
  box.append(lead);

  const lg = document.createElement("div"); lg.className = "legend";
  for (const [c, t] of [[VIB_COLORS.head, "NH₃⁺ head-group vibration (≥20% of the motion)"], [VIB_COLORS.rest, "rest of the molecule"]]) {
    const s = document.createElement("span"); const i = document.createElement("i"); i.style.background = c; s.append(i, document.createTextNode(t)); lg.append(s);
  }
  const dl = document.createElement("span"); dl.className = "vib-steplg"; dl.textContent = "┆ energy step between layers"; lg.append(dl);
  box.append(lg);

  const W = 400, H = 170, M = { l: 8, r: 8, t: 22, b: 30 };
  const X = v => M.l + v / VIB_MAX_MEV * (W - M.l - M.r);
  const Y = v => H - M.b - v * (H - M.t - M.b);
  const svg = vibNS("svg", { viewBox: `0 0 ${W} ${H}`, class: "vibsvg", role: "img",
    "aria-label": `Vibration spectrum of ${m.label}: ${m.modes.length} vibrations; ${headNear.length} of ${ns} energy steps have a head-group vibration nearby` });
  for (const s of VIB.data.steps) {     // ±window band + dashed line + label
    svg.append(vibNS("rect", { x: X(s.meV - VIB.data.window_meV), y: M.t, width: 2 * (X(VIB.data.window_meV) - X(0)), height: H - M.t - M.b, fill: "#ffffff", "fill-opacity": 0.05 }));
    svg.append(vibNS("line", { x1: X(s.meV), x2: X(s.meV), y1: M.t, y2: H - M.b, stroke: "#8a8a8a", "stroke-width": 1, "stroke-dasharray": "3 3" }));
    svg.append(vibNS("text", { x: X(s.meV), y: M.t - 8, "text-anchor": "middle", class: "vib-steptxt" }, s.step.replace("n=", "").replace(" → ", "→").replace("n=", "")));
  }
  svg.append(vibNS("line", { x1: M.l, x2: W - M.r, y1: H - M.b, y2: H - M.b, stroke: "#333", "stroke-width": 1 }));
  for (const t of [0, 100, 200, 300, 400]) svg.append(vibNS("text", { x: X(t), y: H - M.b + 14, "text-anchor": "middle", class: "vib-axis" }, String(t)));
  svg.append(vibNS("text", { x: W - M.r, y: H - 2, "text-anchor": "end", class: "vib-axis" }, "meV"));
  const modes = m.modes.filter(v => v.meV <= VIB_MAX_MEV).sort((a, b) => (a.head >= 0.2) - (b.head >= 0.2));  // head modes on top
  for (const v of modes) {
    const isHead = v.head >= 0.2, x = X(v.meV), y = Y(Math.max(v.ir_rel, 0.03));
    svg.append(vibNS("line", { x1: x, x2: x, y1: H - M.b, y2: y, stroke: isHead ? VIB_COLORS.head : VIB_COLORS.rest, "stroke-width": 2, "stroke-linecap": "round" }));
    const hit = vibNS("rect", { x: x - 4, y: M.t, width: 8, height: H - M.t - M.b, fill: "transparent" });
    if (tip) {
      hit.addEventListener("pointermove", ev => tip(ev, [`${v.meV.toFixed(1)} meV · ${Math.round(v.cm)} cm⁻¹`,
        `IR intensity ${(100 * v.ir_rel).toFixed(0)}% of strongest`, `head-group share ${(100 * v.head).toFixed(0)}%`]));
      hit.addEventListener("pointerleave", () => tip(null));
    }
    svg.append(hit);
  }
  box.append(svg);

  const ul = document.createElement("ul"); ul.className = "vib-list";
  for (const s of m.matches) {
    const li = document.createElement("li");
    li.textContent = `${s.step} (${s.step_meV} meV): ` + (s.n_modes
      ? `${s.n_modes} vibration${s.n_modes > 1 ? "s" : ""} nearby; best head-group share ${(100 * s.best_head_share).toFixed(0)}% at ${s.best_meV} meV`
      : "no vibration nearby");
    ul.append(li);
  }
  box.append(ul);
  const note = document.createElement("p"); note.className = "muted vib-note";
  note.textContent = `${m.cation_smiles} · charge +${m.charge} · ${m.modes.length} vibrations` + (m.n_imaginary ? ` · ${m.n_imaginary} unstable (imaginary) mode(s)` : "") +
    ". GFN2-xTB in implicit water: frequencies typically within 5–10% of experiment; IR heights are for comparison with a lab FTIR spectrum. " +
    "A matching vibration is a hint, not a guarantee: how strongly it couples to the light energy still needs measuring.";
  box.append(note);
  return box;
}
