// Sign-up check shared by every tool page. Anyone can look around; running, saving, deleting, downloading and
// adding need a (free) sign-up. Pages call QD.need("run a simulation", fn): fn runs straight away if signed up,
// otherwise a small sign-up form pops up in place, and fn runs once it succeeds (or QD.onSignup, if a page sets it).
window.QD = (() => {
  let state = fetch("/api/session").then(r => r.ok ? r.json() : null).catch(() => null)
    .then(s => s || { signed_in: true, gated: false });          // no sign-up server (local run): everything open
  const member = () => state.then(s => !s.gated || s.signed_in);
  const st = document.createElement("style");
  st.textContent = `
  .qd-veil { position: fixed; inset: 0; background: rgba(0,0,0,.72); z-index: 200; display: none; align-items: center; justify-content: center; padding: 16px; }
  .qd-veil.open { display: flex; }
  .qd-box { width: 440px; max-width: 100%; max-height: calc(100vh - 32px); overflow: auto; background: #141414; border: 1px solid #262626;
    border-top: 3px solid var(--brand, #76b900); border-radius: 2px; padding: 20px 22px 18px; box-shadow: 0 18px 50px rgba(0,0,0,.7);
    color: var(--text-primary, #f2f2f2); font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
  .qd-box .k { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .1em; color: var(--brand, #76b900); margin-bottom: 6px; }
  .qd-box h3 { margin: 0 0 6px; font-size: 19px; letter-spacing: -.01em; }
  .qd-box p.lead { margin: 0 0 14px; color: var(--text-secondary, #b3b3b3); font-size: 13.5px; }
  .qd-box form { display: grid; gap: 10px; }
  .qd-box label { display: grid; gap: 4px; font-size: 12px; color: var(--text-muted, #8a8a8a); }
  .qd-box label .opt { color: #6a6a6a; }
  .qd-box input:not([type=checkbox]), .qd-box select { font: inherit; color: var(--text-primary, #f2f2f2); background: var(--surface-2, #1c1c1c);
    border: 1px solid #333; border-radius: 2px; padding: 7px 9px; height: 36px; }
  .qd-box input:focus-visible, .qd-box select:focus-visible, .qd-box button:focus-visible { outline: 2px solid var(--brand, #76b900); outline-offset: 2px; }
  .qd-box .two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  @media (max-width: 480px) { .qd-box .two { grid-template-columns: 1fr; } }
  .qd-box .consent { display: flex; gap: 8px; align-items: flex-start; font-size: 12.5px; color: var(--text-secondary, #b3b3b3); }
  .qd-box .consent input { margin-top: 3px; accent-color: var(--brand, #76b900); }
  .qd-box .consent a { color: var(--brand, #76b900); }
  .qd-box .hp { position: absolute; left: -9999px; width: 1px; height: 1px; overflow: hidden; }
  .qd-box .row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 4px; }
  .qd-box button { font: inherit; font-weight: 600; border-radius: 2px; padding: 8px 16px; cursor: pointer; }
  .qd-box button.go { background: var(--brand, #76b900); color: #000; border: 1px solid var(--brand, #76b900); }
  .qd-box button.go:hover { background: var(--brand-hover, #8ccf14); }
  .qd-box button.go:disabled { opacity: .5; cursor: default; }
  .qd-box button.later { background: transparent; color: var(--text-primary, #f2f2f2); border: 1px solid #3a3a3a; }
  .qd-box button.later:hover { border-color: var(--brand, #76b900); }
  .qd-box .msg:empty { display: none; }
  .qd-box .msg { font-size: 13px; color: var(--text-secondary, #b3b3b3); }
  .qd-box .msg.err { color: #ff9a9a; background: rgba(208,59,59,.12); border: 1px solid rgba(208,59,59,.4); padding: 7px 10px; border-radius: 2px; }`;
  document.head.append(st);

  let box, pending = null;
  function build() {
    box = document.createElement("div");
    box.className = "qd-veil";
    box.innerHTML = `<div class="qd-box" role="dialog" aria-modal="true" aria-labelledby="qd-h">
      <div class="k">Free · no password</div><h3 id="qd-h"></h3>
      <p class="lead">Looking around is open to everyone. Tell us who you are once and you can run, save, add and
        download from now on. Your browser stays signed in on this device.</p>
      <form novalidate>
        <div class="two">
          <label>Name <input name="name" autocomplete="name" maxlength="100" required></label>
          <label>Email <input name="email" type="email" autocomplete="email" maxlength="254" required></label>
        </div>
        <div class="two">
          <label><span>Organisation <span class="opt">(optional)</span></span><input name="organisation" autocomplete="organization" maxlength="150"></label>
          <label><span>Role <span class="opt">(optional)</span></span><select name="role"><option value="">Choose one</option>
            <option>Academic researcher</option><option>Industry researcher</option><option>Student</option>
            <option>Materials supplier</option><option>Investor</option><option>Other</option></select></label>
        </div>
        <div class="hp" aria-hidden="true"><label>Website <input name="website" tabindex="-1" autocomplete="off"></label></div>
        <label class="consent"><input type="checkbox" name="consent" value="1">
          <span>I agree to the <a href="/#privacy" target="_blank" rel="noopener">privacy note</a>.</span></label>
        <div class="msg" role="status" aria-live="polite"></div>
        <div class="row"><button class="go" type="submit">Sign up and continue</button><button class="later" type="button">Not now</button></div>
      </form></div>`;
    const form = box.querySelector("form"), msg = box.querySelector(".msg"), go = box.querySelector("button.go");
    box.addEventListener("pointerdown", e => { if (e.target === box) close(); });
    box.querySelector("button.later").onclick = close;
    document.addEventListener("keydown", e => { if (e.key === "Escape" && box.classList.contains("open")) close(); });
    const err = (t, f) => { msg.className = "msg err"; msg.textContent = t; if (f) f.focus(); };
    form.addEventListener("submit", async ev => {
      ev.preventDefault();
      const data = Object.fromEntries(new FormData(form));
      data.consent = form.consent.checked;
      msg.className = "msg"; msg.textContent = "";
      if (!data.name.trim()) return err("Please give your name.", form.name);
      if (!form.email.checkValidity() || !data.email.trim()) return err("Please give a valid email address.", form.email);
      if (!data.consent) return err("Please tick the box to agree to the privacy note.", form.consent);
      go.disabled = true; msg.textContent = "Signing you up…";
      try {
        const r = await fetch("/api/register", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
        const out = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(out.error || "Something went wrong. Please try again.");
        state = Promise.resolve({ signed_in: true, gated: true, name: out.name });
        document.dispatchEvent(new CustomEvent("qd:signedin", { detail: out }));
        const fn = pending; close();
        if (QD.onSignup) QD.onSignup(); else if (fn) fn();
      } catch (e) {
        err(e.message);
      } finally {
        go.disabled = false;
      }
    });
    document.body.append(box);
  }
  function ask(what, fn) {
    if (!box) build();
    pending = fn || null;
    box.querySelector("h3").textContent = "Sign up to " + what + ".";
    box.querySelector(".msg").textContent = "";
    box.classList.add("open");
    box.querySelector("input[name=name]").focus();
  }
  function close() { box.classList.remove("open"); pending = null; }
  async function need(what, fn) {
    if (await member()) return fn && fn();
    ask(what, fn);
  }
  return { member, need, ask, onSignup: null };
})();

// Shared app-launcher ("grid") menu for every page: a nine-dot button in the top bar opens a panel of page tiles
// and dashboard model shortcuts. Keyboard: G toggles, 1-4 jump to a page, arrows move, Esc closes.
(() => {
  const PAGES = [
    { href: "/dashboard", name: "Dynamics dashboard", desc: "Run live quantum simulations (CUDA-Q)", icon: "wave" },
    { href: "/explorer", name: "Materials explorer", desc: "Rank purchasable perovskite recipes", icon: "layers" },
    { href: "/molecules", name: "New molecules", desc: "Design spacers for custom synthesis", icon: "hex" },
    { href: "/chain", name: "Spin chain at scale", desc: "100 spins and the IBM noise preview", icon: "chain" },
  ];
  const MODELS = [
    { model: "funnel", name: "Energy funnel" }, { model: "transmon", name: "Transmon qubit" },
    { model: "cavity", name: "Qubit readout" }, { model: "spinchain", name: "Spin chain" },
  ];
  const ICONS = {   // simple 24px line icons
    grid: '<circle cx="5" cy="5" r="1.8"/><circle cx="12" cy="5" r="1.8"/><circle cx="19" cy="5" r="1.8"/><circle cx="5" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="19" cy="12" r="1.8"/><circle cx="5" cy="19" r="1.8"/><circle cx="12" cy="19" r="1.8"/><circle cx="19" cy="19" r="1.8"/>',
    wave: '<path d="M2 12h3l3-7 4 14 4-10 2 3h4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    layers: '<path d="M12 3 2 8l10 5 10-5-10-5Z M2 13l10 5 10-5 M2 17.5l10 5 10-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>',
    hex: '<path d="M12 2.5 20.5 7.3v9.4L12 21.5 3.5 16.7V7.3Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><circle cx="12" cy="12" r="2.6" fill="currentColor"/>',
    chain: '<circle cx="3.5" cy="12" r="2" fill="currentColor"/><circle cx="9.2" cy="12" r="2" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="14.8" cy="12" r="2" fill="currentColor"/><circle cx="20.5" cy="12" r="2" fill="none" stroke="currentColor" stroke-width="2"/>',
  };
  const svg = (k, size = 22) => `<svg viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true" ${k === "grid" ? 'fill="currentColor"' : ""}>${ICONS[k]}</svg>`;

  const style = document.createElement("style");
  style.textContent = `
  .qnav-btn { display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; border-radius: 50%;
    background: transparent; border: 1px solid transparent; color: var(--text-secondary, #b3b3b3); cursor: pointer; padding: 0; margin-left: 4px; }
  .qnav-btn:hover, .qnav-btn[aria-expanded="true"] { background: #1c1c1c; border-color: #333; color: var(--brand, #76b900); }
  .qnav-btn:focus-visible { outline: 2px solid var(--brand, #76b900); outline-offset: 2px; }
  .qnav-here { color: var(--text-muted, #8a8a8a); font-size: 12px; margin-right: 2px; white-space: nowrap; }
  .qnav-panel { position: fixed; top: 58px; right: 20px; width: 400px; max-width: calc(100vw - 24px); z-index: 100;
    background: #0d0d0d; border: 1px solid #2c2c2c; border-radius: 4px; box-shadow: 0 18px 50px rgba(0,0,0,.7); padding: 14px; display: none; }
  .qnav-panel.open { display: block; }
  .qnav-h { font-size: 11px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--text-muted, #8a8a8a); margin: 2px 4px 8px; }
  .qnav-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
  .qnav-tile { position: relative; display: flex; flex-direction: column; gap: 6px; padding: 12px; border-radius: 3px; border: 1px solid #222;
    background: #141414; color: var(--text-primary, #f2f2f2); text-decoration: none; min-height: 104px; }
  .qnav-tile:hover, .qnav-tile:focus-visible { border-color: var(--brand, #76b900); background: #171d0f; outline: none; }
  .qnav-tile .ic { color: var(--brand, #76b900); }
  .qnav-tile b { font-size: 13.5px; }
  .qnav-tile span.d { font-size: 12px; color: var(--text-muted, #8a8a8a); line-height: 1.35; }
  .qnav-tile kbd, .qnav-foot kbd { font: 600 10.5px ui-monospace, Consolas, monospace; color: var(--text-secondary, #b3b3b3); border: 1px solid #3a3a3a;
    border-bottom-width: 2px; border-radius: 3px; padding: 0 5px; }
  .qnav-tile kbd { position: absolute; top: 10px; right: 10px; }
  .qnav-tile.cur { border-color: #3a4d17; background: #151b0c; }
  .qnav-tile.cur::after { content: "You are here"; position: absolute; bottom: 10px; right: 10px; font-size: 10.5px; color: var(--brand, #76b900); }
  .qnav-models { display: flex; flex-wrap: wrap; gap: 6px; }
  .qnav-chip { font-size: 12.5px; padding: 6px 10px; border: 1px solid #2c2c2c; border-radius: 999px; color: var(--text-secondary, #b3b3b3);
    text-decoration: none; background: #141414; }
  .qnav-chip:hover, .qnav-chip:focus-visible { border-color: var(--brand, #76b900); color: var(--text-primary, #f2f2f2); outline: none; }
  .qnav-chip.cur { border-color: #3a4d17; color: var(--brand, #76b900); }
  .qnav-sep { height: 1px; background: #222; margin: 12px 0; }
  .qnav-foot { font-size: 11.5px; color: var(--text-muted, #8a8a8a); margin-top: 12px; display: flex; gap: 12px; flex-wrap: wrap; }
  .qnav-logo { display: inline-flex; align-items: center; gap: 14px; color: inherit; text-decoration: none; }
  .qnav-logo:hover .brand { color: var(--brand, #76b900); }
  .qnav-logo:focus-visible { outline: 2px solid var(--brand, #76b900); outline-offset: 4px; }
  .qnav-home { color: var(--text-secondary, #b3b3b3); text-decoration: none; font-size: 13px; font-weight: 600; padding: 6px 10px;
    border: 1px solid transparent; }
  .qnav-home:hover, .qnav-home:focus-visible { color: var(--brand, #76b900); border-color: var(--line, #262626); outline: none; }
  .qnav-link { color: var(--text-secondary, #b3b3b3); text-decoration: underline; text-underline-offset: 2px; }
  .qnav-link:first-of-type { margin-left: auto; }
  .qnav-link:hover, .qnav-link:focus-visible { color: var(--brand, #76b900); }
  `;
  document.head.append(style);

  const bar = document.querySelector(".bar-top");
  if (!bar) return;
  bar.querySelectorAll(".navlink").forEach(a => a.remove());          // the menu replaces the old per-page links
  // the logo and name go back to the landing page
  const mark = bar.querySelector(".mark"), brand = bar.querySelector(".brand");
  if (mark && brand && !bar.querySelector(".qnav-logo")) {
    const home = document.createElement("a");
    home.className = "qnav-logo"; home.href = "/"; home.title = "Quantum Dynamics home";
    mark.before(home); home.append(mark, brand);
  }

  const path = location.pathname.replace(/\.html$/, "").replace(/\/$/, "") || "/";
  const curPage = PAGES.find(p => p.href === path) || PAGES[0];
  const onDash = curPage.href === "/dashboard";
  const curModel = () => (onDash && document.getElementById("model")) ? document.getElementById("model").value : null;

  let isMember = true;
  QD.member().then(m => { isMember = m; });
  document.addEventListener("qd:signedin", () => { isMember = true; });
  const here = document.createElement("span");
  here.className = "qnav-here"; here.textContent = curPage.name;
  const btn = document.createElement("button");
  btn.className = "qnav-btn"; btn.type = "button"; btn.innerHTML = svg("grid", 20);
  btn.setAttribute("aria-label", "Open page menu"); btn.setAttribute("aria-haspopup", "true");
  btn.setAttribute("aria-expanded", "false"); btn.setAttribute("aria-controls", "qnav-panel"); btn.title = "Pages (G)";
  const homeLink = document.createElement("a");
  homeLink.className = "qnav-home"; homeLink.href = "/"; homeLink.textContent = "Home";
  bar.append(homeLink, here, btn);

  const panel = document.createElement("div");
  panel.className = "qnav-panel"; panel.id = "qnav-panel"; panel.setAttribute("role", "dialog"); panel.setAttribute("aria-label", "Pages");
  document.body.append(panel);

  function build() {
    const cm = curModel();
    panel.innerHTML =
      `<div class="qnav-h">Pages</div><div class="qnav-grid">` +
      PAGES.map((p, i) => `<a class="qnav-tile${p === curPage ? " cur" : ""}" href="${p.href}" data-i="${i}"${p === curPage ? ' aria-current="page"' : ""}>` +
        `<span class="ic">${svg(p.icon)}</span><b>${p.name}</b><span class="d">${p.desc}</span><kbd>${i + 1}</kbd></a>`).join("") +
      `</div><div class="qnav-sep"></div><div class="qnav-h">Simulation models</div><div class="qnav-models">` +
      MODELS.map(m => `<a class="qnav-chip${m.model === cm ? " cur" : ""}" href="/dashboard#model=${m.model}" data-model="${m.model}">${m.name}</a>`).join("") +
      `</div><div class="qnav-foot"><span><kbd>G</kbd> menu</span><span><kbd>1</kbd>–<kbd>4</kbd> pages</span><span><kbd>Esc</kbd> close</span>` +
      `<a class="qnav-link" href="/">Home</a>` + (isMember ? `<a class="qnav-link" href="#" data-signout>Sign out</a>` : "") + `</div>`;
    const so = panel.querySelector("[data-signout]");
    if (so) so.addEventListener("click", async ev => {
      ev.preventDefault();
      await fetch("/api/logout", { method: "POST" }).catch(() => null);
      location.href = "/";
    });
    panel.querySelectorAll("[data-model]").forEach(a => a.addEventListener("click", ev => {
      const sel = onDash && document.getElementById("model");
      if (sel) {                                      // already on the dashboard: switch model in place
        ev.preventDefault();
        sel.value = a.dataset.model; sel.dispatchEvent(new Event("change", { bubbles: true }));
        history.replaceState(null, "", "#model=" + a.dataset.model);
        close(false);
      }
    }));
  }
  const items = () => [...panel.querySelectorAll("a")];
  function open() {
    build(); panel.classList.add("open"); btn.setAttribute("aria-expanded", "true");
    const r = btn.getBoundingClientRect();
    panel.style.top = (r.bottom + 8) + "px";
    panel.style.right = Math.max(12, innerWidth - r.right - 4) + "px";
    (panel.querySelector(".qnav-tile.cur") || items()[0]).focus();
  }
  function close(refocus = true) {
    panel.classList.remove("open"); btn.setAttribute("aria-expanded", "false");
    if (refocus) btn.focus();
  }
  const isOpen = () => panel.classList.contains("open");
  btn.addEventListener("click", () => isOpen() ? close() : open());
  document.addEventListener("pointerdown", e => { if (isOpen() && !panel.contains(e.target) && !btn.contains(e.target)) close(false); });
  document.addEventListener("keydown", e => {
    const typing = /^(INPUT|SELECT|TEXTAREA)$/.test((e.target.tagName || "")) || e.target.isContentEditable;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (!isOpen()) {
      if (!typing && (e.key === "g" || e.key === "G")) { e.preventDefault(); open(); }
      return;
    }
    if (e.key === "Escape") { e.preventDefault(); close(); return; }
    if (/^[1-4]$/.test(e.key)) { e.preventDefault(); location.href = PAGES[+e.key - 1].href; return; }
    if (e.key === "g" || e.key === "G") { e.preventDefault(); close(); return; }
    const list = items(), i = list.indexOf(document.activeElement);
    const move = { ArrowRight: 1, ArrowDown: e.target.classList.contains("qnav-tile") ? 2 : 1, ArrowLeft: -1, ArrowUp: e.target.classList.contains("qnav-tile") ? -2 : -1 }[e.key];
    if (move) { e.preventDefault(); list[Math.max(0, Math.min(list.length - 1, (i < 0 ? 0 : i + move)))].focus(); }
    if (e.key === "Tab") {                          // keep focus inside the open menu
      const first = list[0], last = list[list.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
  addEventListener("resize", () => { if (isOpen()) open(); });
})();
