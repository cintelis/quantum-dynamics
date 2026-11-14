// Home page "Contact us" box: an envelope travels from "You" to us along the upper arc, we light up, and a reply
// comes back along the lower arc. Built with Anime.js v4 (vendored /anime.esm.min.js). Plays only while the box is
// open and on screen; a still picture if reduced motion is on.
import { createTimeline, svg as asvg, utils } from "/anime.esm.min.js";

const root = document.getElementById("contactAnim"), box = document.getElementById("contact");
if (root && box) {
  const NS = "http://www.w3.org/2000/svg";
  const BRAND = "#76b900", LINE = "#3a3a3a", INK = "#b3b3b3", MUTED = "#8a8a8a";
  const el = (tag, a = {}, text) => {
    const e = document.createElementNS(NS, tag);
    for (const k in a) e.setAttribute(k, a[k]);
    if (text != null) e.textContent = text;
    return e;
  };
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const s = el("svg", { viewBox: "0 0 260 200", class: "cta-svg" });
  root.append(s);

  const YOU = [36, 100], US = [224, 100];
  const out = el("path", { d: "M52 90 C 100 26, 160 26, 208 90", fill: "none", stroke: LINE, "stroke-width": 1.5, "stroke-dasharray": "3 4" });
  const back = el("path", { d: "M208 110 C 160 174, 100 174, 52 110", fill: "none", stroke: LINE, "stroke-width": 1.5, "stroke-dasharray": "3 4" });
  s.append(out, back,
    el("text", { x: 130, y: 30, "text-anchor": "middle", fill: MUTED, "font-size": 10, "letter-spacing": ".1em" }, "YOUR MESSAGE"),
    el("text", { x: 130, y: 182, "text-anchor": "middle", fill: MUTED, "font-size": 10, "letter-spacing": ".1em" }, "OUR REPLY"));

  // you: a person in a circle
  const youRing = el("circle", { cx: YOU[0], cy: YOU[1], r: 16, fill: "#1c1c1c", stroke: LINE, "stroke-width": 1.5 });
  const youPulse = el("circle", { cx: YOU[0], cy: YOU[1], r: 16, fill: "none", stroke: BRAND, "stroke-width": 1.5, opacity: 0 });
  s.append(youPulse, youRing,
    el("circle", { cx: YOU[0], cy: YOU[1] - 4, r: 4, fill: INK }),
    el("path", { d: `M${YOU[0] - 7} ${YOU[1] + 9}a7 6 0 0 1 14 0`, fill: INK }),
    el("text", { x: YOU[0], y: YOU[1] + 32, "text-anchor": "middle", fill: INK, "font-size": 10, "letter-spacing": ".1em" }, "YOU"));

  // us: the brand mark
  const usPulse = el("circle", { cx: US[0], cy: US[1], r: 16, fill: "none", stroke: BRAND, "stroke-width": 1.5, opacity: 0 });
  const usBox = el("circle", { cx: US[0], cy: US[1], r: 16, fill: "#1c1c1c", stroke: LINE, "stroke-width": 1.5 });
  const [ux, uy] = US;
  const usMark = el("polygon", { points: `${ux - 4.7},${uy - 6} ${ux + 7.3},${uy - 6} ${ux + 4.7},${uy + 6} ${ux - 7.3},${uy + 6}`, fill: BRAND });
  s.append(usPulse, usBox, usMark,
    el("text", { x: US[0], y: US[1] + 32, "text-anchor": "middle", fill: INK, "font-size": 10, "letter-spacing": ".1em" }, "US"));

  // the travellers, drawn around (0,0) so the motion path can move them
  const trail = [0, 1, 2].map(i => { const c = el("circle", { r: 2 - i * .5, fill: INK, opacity: 0 }); s.append(c); return c; });
  const env = el("g", { opacity: 0 });
  env.append(el("rect", { x: -9, y: -6, width: 18, height: 12, rx: 1.5, fill: "#1c1c1c", stroke: INK, "stroke-width": 1.4 }),
             el("path", { d: "M-8 -5l8 6 8-6", fill: "none", stroke: INK, "stroke-width": 1.4 }));
  s.append(env);
  const reply = el("g", { opacity: 0 });
  reply.append(el("circle", { r: 7, fill: BRAND }), el("path", { d: "M-3.2 0l2.2 2.2 4-4.4", fill: "none", stroke: "#000", "stroke-width": 1.6, "stroke-linecap": "round", "stroke-linejoin": "round" }));
  s.append(reply);

  if (still) {
    env.setAttribute("opacity", 1); env.setAttribute("transform", "translate(130 42)");
    reply.setAttribute("opacity", 1); reply.setAttribute("transform", "translate(130 158)");
  } else {
    const ride = (path, offset = 0) => { const m = asvg.createMotionPath(path, offset); delete m.rotate; return m; };
    const pulse = c => ({ r: [16, 30], opacity: [.9, 0], duration: 700, ease: "outQuad" });
    const tl = createTimeline({ loop: true, autoplay: false, loopDelay: 900 })
      .add(env, { opacity: [{ to: 1, duration: 150 }, { to: 1, duration: 1250 }, { to: 0, duration: 200 }], ...ride(out), duration: 1600, ease: "inOutSine" }, 0);
    trail.forEach((c, i) => tl.add(c, { opacity: [{ to: .8 - i * .2, duration: 150 }, { to: .8 - i * .2, duration: 1150 }, { to: 0, duration: 200 }],
      ...ride(out, -(i + 1) * .045), duration: 1500, ease: "inOutSine" }, 90 * (i + 1)));
    tl.add(usPulse, pulse(), 1550)
      .add(usBox, { stroke: [BRAND, LINE], duration: 900, ease: "outQuad" }, 1550)
      .add(reply, { opacity: [{ to: 1, duration: 150 }, { to: 1, duration: 1250 }, { to: 0, duration: 200 }], ...ride(back), duration: 1600, ease: "inOutSine" }, 2300)
      .add(youPulse, pulse(), 3850)
      .add(youRing, { stroke: [BRAND, LINE], duration: 900, ease: "outQuad" }, 3850);

    // play only while open and visible
    let visible = false;
    const sync = () => (box.open && visible) ? tl.play() : tl.pause();
    new IntersectionObserver(([e]) => { visible = e.isIntersecting; sync(); }).observe(root);
    box.addEventListener("toggle", sync);
  }
}
