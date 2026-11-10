(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const NS = "http://www.w3.org/2000/svg";
  const root = document.documentElement;
  const body = document.body;
  const main = $("main");
  const app = $(".app");
  const SID = body.dataset.story || "story";
  // a tour shows code at one commit: no diff, so no split, full diff or reviewed marks
  const TOUR = body.dataset.mode === "tour";
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const narrow = matchMedia("(max-width: 900px)");
  const smooth = () => (reduced ? "auto" : "smooth");
  const store = {
    get(k, d) {
      try {
        const v = localStorage.getItem(`${SID}:${k}`);
        return v === null ? d : JSON.parse(v);
      } catch {
        return d;
      }
    },
    set(k, v) {
      try {
        localStorage.setItem(`${SID}:${k}`, JSON.stringify(v));
      } catch {}
    },
  };
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  let traceNames = {};
  try {
    traceNames = JSON.parse(body.dataset.traces || "{}");
  } catch {}

  const flash = (el) => {
    el.classList.remove("flash");
    void el.offsetWidth;
    el.classList.add("flash");
  };
  // code colours: the page's own palette, or one of the Pygments themes build.py adds
  let synNames = {};
  try {
    synNames = JSON.parse(body.dataset.syns || "{}");
  } catch {}
  const synDefault = body.dataset.syn || "";
  const synList = [...Object.keys(synNames), ""];
  const synLabel = (s) => `${s ? synNames[s] : "Glass"}${s === synDefault ? " (default)" : ""}`;
  const synPick = $("#syn-pick");
  synPick.append(...synList.map((s) => new Option(synLabel(s), s)));
  function setSyn(s, say) {
    if (!synList.includes(s)) s = "";
    if (s) body.dataset.syn = s;
    else delete body.dataset.syn;
    synPick.value = s;
    try {
      localStorage.setItem("code-story:code-theme", s);
    } catch {}
    if (say) toast(`Code colours: ${synLabel(s)} (${synList.indexOf(s) + 1} of ${synList.length})`);
  }
  synPick.addEventListener("change", () => setSyn(synPick.value));
  try {
    setSyn(localStorage.getItem("code-story:code-theme") ?? synDefault);
  } catch {}

  const toastEl = $(".toast");
  let toastT = 0;
  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.add("show");
    clearTimeout(toastT);
    toastT = setTimeout(() => toastEl.classList.remove("show"), 1600);
  }

  // ---------- header: hides while reading down, returns on the way up ----------

  let lastY = scrollY;
  let travel = 0; // how far the scroll has run in its current direction
  let ptrY = Infinity;
  let hdrHidden = false;
  let quietUntil = 0;
  // scrolls the page makes itself (jumps, layout changes) must not hide the header
  const quiet = (ms = 1000) => (quietUntil = performance.now() + ms);
  function setHdr(hide) {
    if (hide === hdrHidden) return;
    hdrHidden = hide;
    body.classList.toggle("hdr-hidden", hide);
  }
  function onScrollHdr() {
    const y = scrollY;
    const now = performance.now();
    if (now < quietUntil) {
      // a long smooth scroll outlasts the window; keep it open until the scroll stops
      quietUntil = Math.max(quietUntil, now + 160);
      lastY = y;
      travel = 0;
      return;
    }
    const d = y - lastY;
    if (!d) return;
    lastY = y;
    travel = d > 0 === travel > 0 ? travel + d : d;
    // a few pixels back and forth (a resting hand, the tail of a fling) must not flip the header each time
    if (Math.abs(travel) < 24) return;
    if (travel < 0) setHdr(false);
    // nor may scrolling hide it from under the pointer, to be shown again by the pointer's next twitch
    else if (y > 160 && pop.hidden && ptrY >= 56) setHdr(true);
  }
  addEventListener("mousemove", (e) => {
    ptrY = e.clientY;
    if (hdrHidden && ptrY < 56) setHdr(false);
  });
  root.addEventListener("mouseleave", () => (ptrY = Infinity));
  addEventListener("focusin", (e) => {
    if (e.target.closest && e.target.closest(".hdr")) setHdr(false);
  });

  // keep whatever the reader is looking at in place while the layout above it changes
  // returns a resolver, so a code line is found again in whichever view shows it next
  function anchorFor() {
    const left = main.getBoundingClientRect().left + parseFloat(getComputedStyle(main).paddingLeft);
    const xs = [left + 160, left + (innerWidth - left) * 0.4];
    for (const y of [170, 260, 380, 520]) {
      for (const pass of [".row, .srow", ".prose, .lede, h1, h2, h3, .fork, .fh, .gap"])
        for (const x of xs)
          for (const el of document.elementsFromPoint(x, y)) {
            if (!main.contains(el) || el.closest(".note.review")) continue;
            const a = el.closest(pass);
            if (!a) continue;
            if (a.matches(".srow")) {
              const r = a._R || a._L;
              return () => shown(r);
            }
            return a.matches(".row") ? () => shown(a) : () => a;
          }
    }
    return null;
  }
  let anchorRun = 0;
  // wheel and touch are heard only while a run lasts: a standing wheel listener costs a hit test per scroll step
  const HANDS = ["wheel", "touchmove"];
  const cancelAnchor = () => {
    anchorRun++;
    for (const t of HANDS) removeEventListener(t, cancelAnchor);
  };
  addEventListener("pointerdown", cancelAnchor, true);
  function keepAnchor(fn, ms = 480) {
    const run = ++anchorRun;
    const at = anchorFor();
    const t0 = at ? at().getBoundingClientRect().top : 0;
    fn();
    if (!at) return;
    for (const t of HANDS) addEventListener(t, cancelAnchor, { passive: true });
    quiet(ms + 300);
    const end = performance.now() + ms;
    const tick = () => {
      if (run !== anchorRun) return;
      const el = at();
      if (el.getClientRects().length) {
        const d = el.getBoundingClientRect().top - t0;
        if (Math.abs(d) > 0.5) scrollTo({ top: scrollY + d, behavior: "instant" });
      }
      if (performance.now() < end) requestAnimationFrame(tick);
      else cancelAnchor();
    };
    tick();
  }

  // open whatever hides `el`: a closed branch or <details>
  function reveal(el) {
    const brs = [];
    for (let b = el.closest(".branch-wrap"); b; b = b.parentElement.closest(".branch-wrap")) brs.unshift(b);
    for (const br of brs) if (!br.classList.contains("open")) setBranch(br, true, { instant: true });
    for (let d = el.closest("details"); d; d = d.parentElement && d.parentElement.closest("details")) d.open = true;
    const f = el.closest("figure.frame");
    if (f && f !== el && !el.closest(".fh")) setFrame(f, false);
  }
  // what stands in for `el` on screen: its copy in the split view while that shows
  const vis = (el) => (el._c && el.parentElement.hidden ? el._c : el);
  function goTo(el, { block = "start", glow = true } = {}) {
    reveal(el);
    quiet();
    el.scrollIntoView({ behavior: smooth(), block });
    if (glow) flash(el);
  }

  // ---------- split view, generated from the unified rows ----------

  const frames = $$("figure.frame", main);
  const diffFrames = frames.filter((f) => f.classList.contains("diff"));
  const kindOf = (row) => (row.classList.contains("a") ? "a" : row.classList.contains("d") ? "d" : "c");

  function half(row, side) {
    const h = document.createElement("div");
    h.dataset.side = side;
    if (!row) {
      h.className = "half e";
      h.innerHTML = '<span class="ln"></span><span class="sg"></span><code></code>';
      return h;
    }
    const n = side === "L" ? row.dataset.o : row.dataset.n;
    h.className = `half ${kindOf(row)}${row.classList.contains("x") ? " x" : ""}`;
    h.dataset.line = n;
    h.innerHTML = `<span class="ln">${n}</span>${row.querySelector(".sg").outerHTML}${row.querySelector("code").outerHTML}`;
    return h;
  }
  function srow(l, r) {
    const s = document.createElement("div");
    s.className = "srow";
    const hl = half(l, "L");
    const hr = half(r, "R");
    s.append(hl, hr);
    s._L = l;
    s._R = r;
    for (const [x, h] of [
      [l, hl],
      [r, hr],
    ])
      if (x) {
        x._s = s;
        if (l !== r) x._h = h;
        else x[h.dataset.side === "L" ? "_hL" : "_hR"] = h;
      }
    if ([l, r].some((x) => x && x.classList.contains("has-link"))) s.classList.add("has-link");
    return s;
  }
  function buildSplit(u) {
    const s = document.createElement("div");
    s.className = "code s";
    s.hidden = true;
    const kids = [...u.children];
    for (let i = 0; i < kids.length; ) {
      const k = kids[i];
      if (!k.classList.contains("row")) {
        const c = k.cloneNode(true);
        c.removeAttribute("id");
        c._u = k;
        k._c = c;
        s.append(c);
        i++;
        continue;
      }
      if (kindOf(k) === "c") {
        s.append(srow(k, k));
        i++;
        continue;
      }
      const dels = [];
      const adds = [];
      while (i < kids.length && kids[i].classList.contains("d")) dels.push(kids[i++]);
      while (i < kids.length && kids[i].classList.contains("a")) adds.push(kids[i++]);
      for (let x = 0; x < Math.max(dels.length, adds.length); x++) s.append(srow(dels[x], adds[x]));
    }
    u.after(s);
    return s;
  }
  const hasSplit = (u) => u.nextElementSibling && u.nextElementSibling.matches(".code.s");
  const SPLITTABLE = "figure.frame.diff > .code.u, .rip-site > .code.u, details.file-item > .code.u, .fd-body > .code.u";

  let view = store.get("view", "unified");
  // halves are unreadable below this content width (phones, or a wide map beside a small window)
  const SPLIT_MIN = 760;
  // the story column's own width, without the map's lane and the gutters
  const COL_MIN = 680;
  const colW = () => {
    const cs = getComputedStyle(main);
    return main.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  };
  let roomy = colW() >= COL_MIN;
  // the full diff has its own width (its file list is resizable), so it is gated on its own
  let fdRoomy = true;
  const canSplit = () => !TOUR && !narrow.matches && roomy;
  const effView = () => (canSplit() ? view : "unified");
  function syncView(u, on = effView() === "split") {
    const here = on && (fdRoomy || !u.closest("#files"));
    // halves are built on first use, and never for rows the page hasn't filled in yet
    if (!hasSplit(u) && (!here || (u._lazy && !u._done))) return;
    const s = hasSplit(u) ? u.nextElementSibling : buildSplit(u);
    u.hidden = here;
    s.hidden = !here;
  }
  function syncViews() {
    const on = effView() === "split";
    for (const u of $$(SPLITTABLE)) syncView(u, on);
  }
  function applyView() {
    const on = effView() === "split";
    syncViews();
    $$('[data-act="view"]').forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset.view === effView()));
      if (b.dataset.view === "split") {
        b.disabled = !canSplit();
        b.title = canSplit() ? "Split view (s)" : "Needs a wider window, or a narrower map";
      }
    });
    body.classList.toggle("view-split", on);
    paintRows();
    queueWires();
  }
  function setView(v) {
    if (v === "split" && !canSplit()) return toast("Split needs a wider window, or a narrower map");
    view = v;
    store.set("view", v);
    keepAnchor(applyView, 120);
  }

  // ---------- more of a file: each one is packed into the page once and inflated when asked for ----------

  const STEP = 20;
  let srcMeta = [];
  try {
    srcMeta = JSON.parse($("#_src")?.textContent || "[]");
  } catch {}
  const canInflate = "DecompressionStream" in window;
  const srcs = new Map();
  // a source's lines ("-<code>…</code>": the row's sign, then its code) with their old and new line numbers
  function source(i) {
    if (!srcs.has(i))
      srcs.set(
        i,
        (async () => {
          const bytes = Uint8Array.from(atob($(`#_s${i}`).textContent), (c) => c.charCodeAt(0));
          const text = await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate"))).text();
          const lines = text.split("\n");
          const O = new Int32Array(lines.length);
          const N = new Int32Array(lines.length);
          const hs = srcMeta[i].h || [];
          let o = 1;
          let n = 1;
          let h = 0;
          for (let k = 0; k < lines.length; k++) {
            if (h < hs.length && hs[h][0] === k) [, , o, n] = hs[h++];
            const c = lines[k][0];
            if (c !== "+") O[k] = o++;
            if (c !== "-") N[k] = n++;
          }
          return { lines, O, N, plain: !!srcMeta[i].p };
        })(),
      );
    return srcs.get(i);
  }
  const noSource = () => toast("This browser can't unpack the page's code");
  const KINDS = { " ": "c", "-": "d", "+": "a" };
  function makeRows(src, a, b, cls) {
    let html = "";
    for (let k = a; k < b; k++) {
      const ln = src.lines[k];
      const o = src.O[k] || "";
      const n = src.N[k] || "";
      html += src.plain
        ? `<div class="row c${cls}" data-n="${n}"><span class="ln"></span><span class="ln">${n}</span><span class="sg"> </span>${ln.slice(1)}</div>`
        : `<div class="row ${KINDS[ln[0]]}${cls}" data-o="${o}" data-n="${n}"><span class="ln">${o}</span><span class="ln">${n}</span><span class="sg">${ln[0]}</span>${ln.slice(1)}</div>`;
    }
    const t = document.createElement("template");
    t.innerHTML = html;
    let k = a;
    for (const r of t.content.children) r._i = k++;
    return t.content;
  }

  const isRow = (el) => el.classList.contains("row");
  const rowBefore = (el) => {
    for (let e = el.previousElementSibling; e; e = e.previousElementSibling) if (isRow(e)) return e;
  };
  const rowAfter = (el) => {
    for (let e = el.nextElementSibling; e; e = e.nextElementSibling) if (isRow(e)) return e;
  };
  const gapsOf = (u) => [...u.children].filter((el) => el._hi != null);
  function newGap(u, lo, hi, before) {
    const g = document.createElement("div");
    g.className = "gap gj";
    g.innerHTML = "<span></span>";
    g._lo = lo;
    g._hi = hi;
    u.insertBefore(g, before);
  }
  // number the rows a container shows by their place in its source, and note what each break hides
  function setup(u) {
    const m = srcMeta[u.dataset.src];
    const x = m.x && canInflate;
    let idx = 0;
    let first = u.dataset.at;
    for (const el of [...u.children]) {
      if (isRow(el)) {
        if (first != null) {
          if (x && +first > idx) newGap(u, idx, +first, el);
          idx = +first;
          first = null;
        }
        el._i = idx++;
      } else if (el.dataset.at != null) {
        first = null;
        el._lo = x ? idx : +el.dataset.at;
        el._hi = idx = +el.dataset.at;
      }
    }
    if (x && idx < m.n) newGap(u, idx, m.n, null);
    gapsOf(u).forEach((g) => drawGap(g));
  }
  const icon = (d, dots) => `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="${d}"/><path class="dots" d="${dots}"/></svg>`;
  const ICON = {
    up: icon("M8 13.5v-8M4.5 8.5L8 5l3.5 3.5", "M2.5 2.5h11"),
    down: icon("M8 2.5v8M4.5 7.5L8 11l3.5-3.5", "M2.5 13.5h11"),
    all: icon("M8 6V1.5M5.5 4L8 1.5 10.5 4M8 10v4.5M5.5 12L8 14.5l2.5-2.5", "M2.5 8h11"),
    fold: icon("M8 1.5V6M5.5 3.5L8 6l2.5-2.5M8 14.5V10M5.5 12.5L8 10l2.5 2.5", "M2.5 8h11"),
  };
  // a gap's buttons and words, from what it still hides; `src` lets it name the lines
  function drawGap(g, src) {
    const n = g._hi - g._lo;
    const header = g.classList.contains("fd-hh");
    let gx = g.querySelector(":scope > .gx");
    if (n <= 0) {
      gx?.remove();
      g.classList.remove("has-x");
      // a hunk header stays; a break written by the build hides, so folding back can restore it
      if (g.classList.contains("gj")) g.remove();
      else if (!header) g.hidden = !!g._spent || !g.textContent.trim();
      return;
    }
    const lead = !rowBefore(g);
    const trail = !rowAfter(g);
    const acts = n <= STEP ? ["all"] : lead ? ["up", "all"] : trail ? ["down", "all"] : ["up", "down", "all"];
    if (!gx) {
      gx = document.createElement("span");
      gx.className = "gx";
      g.prepend(gx);
      g.classList.add("has-x");
    }
    if (gx._acts !== String(acts)) {
      gx._acts = String(acts);
      gx.innerHTML = acts.map((a) => `<button type="button" class="gb" data-act="unfold" data-x="${a}">${ICON[a]}</button>`).join("");
    }
    const lines = (k) => `${k} line${k === 1 ? "" : "s"}`;
    const say = { up: `Expand up: ${STEP} more lines`, down: `Expand down: ${STEP} more lines`, all: `Show all ${lines(n)} hidden here (shift-click: the whole file)` };
    for (const b of gx.children) b.setAttribute("aria-label", (b.title = say[b.dataset.x]));
    if (header) return;
    const label = g.querySelector(":scope > span:not(.gx)");
    if (g._txt == null) g._txt = label.textContent;
    if (lead) label.textContent = `${lines(n)} above`;
    else if (trail) label.textContent = `${lines(n)} below`;
    else if (src) {
      let a = 0;
      let b = 0;
      let changed = false;
      for (let k = g._lo; k < g._hi; k++) {
        if (src.N[k]) (a = a || src.N[k]), (b = src.N[k]);
        changed = changed || src.lines[k][0] !== " ";
      }
      label.textContent = a ? `${a === b ? `line ${a}` : `lines ${a}–${b}`} ${changed ? "not shown" : "unchanged"}` : `${lines(n)} not shown`;
    }
  }
  // run fn, then scroll so `ref` (a row or a gap) sits where it did
  function holding(ref, u, fn) {
    const el = () => (!ref || !ref.isConnected || ref.hidden ? null : isRow(ref) ? shown(ref) : vis(ref));
    const top = el()?.getBoundingClientRect().top;
    fn();
    const now = el();
    if (top == null || !now) return;
    const d = now.getBoundingClientRect().top - top;
    if (Math.abs(d) < 0.5) return;
    cancelAnchor();
    quiet(600);
    const box = u.closest(".files-body, .def-body");
    if (box) box.scrollTop += d;
    else scrollTo({ top: scrollY + d, behavior: "instant" });
  }
  // a container's rows changed: rebuild its split copy and the things drawn against it
  function touched(u) {
    if (hasSplit(u)) {
      const old = u.nextElementSibling;
      buildSplit(u).hidden = old.hidden;
      old.remove();
    }
    const host = u.closest(HOST);
    if (!host) return void (u.closest("#def") && placeDef());
    const any = !!host.querySelector(".row.x");
    if (any && !host._fold) {
      const b = (host._fold = document.createElement("button"));
      b.type = "button";
      b.className = "fbtn ico";
      b.dataset.act = "refold";
      b.setAttribute("aria-label", (b.title = "Hide the lines you unfolded"));
      b.innerHTML = ICON.fold;
      if (host.matches("figure")) $(".fh-r", host).prepend(b);
      else $(host.matches("details") ? "summary" : ".fd-head", host).append(b);
    }
    if (host._fold) host._fold.hidden = !any;
    paintRows();
    queueWires();
  }
  function open1(g, dir, src, n = STEP) {
    let a = g._lo;
    let b = g._hi;
    if (dir === "down") b = Math.min(b, a + n);
    if (dir === "up") a = Math.max(a, b - n);
    const rows = makeRows(src, a, b, " x");
    if (traceOn) for (const t of rows.querySelectorAll(`.tr[data-tr="${traceOn}"]`)) t.classList.add("on");
    if (dir === "up") g.after(rows), (g._hi = a);
    else g.before(rows), (g._lo = b);
    g._spent = g._hi <= g._lo;
    drawGap(g, src);
  }
  async function unfold(g, dir, whole) {
    const u = g.parentElement;
    let src;
    try {
      src = await source(u.dataset.src);
    } catch {
      return noSource();
    }
    if (g.parentElement !== u || g._hi <= g._lo) return;
    const focused = document.activeElement?.closest(".gap") === vis(g);
    // a step down keeps its button under the pointer; everything else keeps the code that was already there
    const ref = whole || dir === "all" ? (rowBefore(g) ? rowBefore(g) : rowAfter(g)) : dir === "down" ? g : null;
    holding(ref, u, () => {
      if (whole) for (const x of gapsOf(u)) x._hi > x._lo && open1(x, "all", src);
      else open1(g, dir, src);
      touched(u);
    });
    if (focused && g.isConnected) (vis(g).querySelector(`[data-x="${dir}"]`) || vis(g).querySelector(".gb"))?.focus({ preventScroll: true });
  }
  function refold(host) {
    const us = $$(".code.u[data-src]", host).filter((u) => u.closest(HOST) === host);
    const kept = us.flatMap((u) => [...u.children].filter((el) => isRow(el) && !el.classList.contains("x")));
    // keep the first of the story's own rows that is still on screen where it is
    const ref = kept.find((r) => shown(r).getBoundingClientRect().bottom > 100) || kept[kept.length - 1];
    holding(ref, us[0], () => {
      for (const u of us) {
        if (!u.querySelector(":scope > .x")) continue;
        for (const el of [...u.children]) {
          if (el.classList.contains("x") || el.classList.contains("gj")) el.remove();
          else if (el._hi != null) {
            el.hidden = false;
            el._spent = false;
            if (el._txt != null) el.querySelector(":scope > span:not(.gx)").textContent = el._txt;
          }
        }
        setup(u);
        touched(u);
      }
    });
    if (sel.rows.some((r) => !r.isConnected)) select(sel.host, sel.rows.filter((r) => r.isConnected));
    if (anchor && !anchor.isConnected) anchor = null;
  }
  // A link can name lines its reader had unfolded. Unfold from the nearer edge of each break as far as
  // the lines `keys` name ("R120", "L7"), so the link finds them again.
  async function expose(host, keys) {
    for (const u of $$(".code.u[data-src]", host)) {
      if (u.closest(HOST) !== host || !srcMeta[u.dataset.src].x || !canInflate) continue;
      const src = await source(u.dataset.src).catch(() => null);
      const at = src ? keys.map((k) => (k[0] === "L" ? src.O : src.N).indexOf(+k.slice(1))) : [];
      if (at.includes(-1) || !at.length) continue;
      const lo = Math.min(...at);
      const hi = Math.max(...at) + 1;
      let changed = false;
      for (const g of gapsOf(u)) {
        const a = Math.max(g._lo, lo);
        const b = Math.min(g._hi, hi);
        if (a >= b) continue;
        if (b - g._lo <= g._hi - a) open1(g, "down", src, b - g._lo);
        else open1(g, "up", src, g._hi - a);
        changed = true;
      }
      if (changed) touched(u);
    }
  }
  // rows the page left out (the full diff, files outside the story) come from the source on first use
  function ready(u) {
    if (!u._lazy) return Promise.resolve();
    return (u._ready ||= source(u.dataset.src).then((src) => {
      // in the open full diff a file may fill in above the reader: what they see must not move.
      // Only a file wholly above counts; one the reader is inside grows below them.
      const box = !files.hidden && u.closest(".files-body");
      const above = box && u.getBoundingClientRect().bottom <= box.getBoundingClientRect().top;
      const h = above ? u.parentElement.offsetHeight : 0;
      for (const g of [...u.children]) {
        const a = +g.dataset.at;
        if (g.dataset.len != null) g.after(makeRows(src, a, a + +g.dataset.len, ""));
      }
      u._done = true;
      u.style.minHeight = "";
      setup(u);
      syncView(u);
      if (above) box.scrollTop += u.parentElement.offsetHeight - h;
    }, noSource));
  }
  const fillIn = (el) => Promise.all($$(".code.u[data-src]", el).map(ready));

  // ---------- definitions: a name with data-d opens where it is defined, from the page's own sources ----------

  let defMeta = [];
  try {
    defMeta = JSON.parse($("#_def")?.textContent || "[]");
  } catch {}
  const defEl = $("#def");
  const defBody = $(".def-body", defEl);
  let defNow = null; // { ids, k }: the candidates of the name that was clicked, and the one on show
  const defHead = $(".def-h", defEl);
  let defPos = null; // where the reader dragged the panel; null while the page decides
  // Put the panel where the reader left it, else top right, and inside the window. Opened by a click at
  // `pt`, it never lands on the name that was clicked: it goes under that line, or above it.
  function placeDef(pt) {
    if (defEl.hidden) return;
    if (narrow.matches) return void (defEl.style.left = defEl.style.top = defEl.style.right = "");
    const w = defEl.offsetWidth;
    const h = defEl.offsetHeight;
    const keep = !pt && defEl.style.left;
    const left = clamp(keep ? defEl.offsetLeft : defPos ? defPos.x : innerWidth, 8, Math.max(8, innerWidth - w - 12));
    let top = clamp(keep ? defEl.offsetTop : defPos ? defPos.y : 64, 8, Math.max(8, innerHeight - h - 8));
    if (pt && pt.x > left - 8 && pt.x < left + w + 8 && pt.y > top - 8 && pt.y < top + h + 8) {
      const below = pt.y + 22;
      const above = pt.y - 22 - h;
      top = below + h <= innerHeight - 8 ? below : above >= 8 ? above : pt.y < innerHeight / 2 ? innerHeight - h - 8 : 8;
    }
    defEl.style.left = `${left}px`;
    defEl.style.top = `${top}px`;
    defEl.style.right = "auto";
  }
  defHead.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || narrow.matches || e.target.closest("button, .path")) return;
    e.preventDefault();
    defHead.setPointerCapture(e.pointerId);
    // measured once: a move only sets a transform, which costs no layout and no paint
    const x0 = defEl.offsetLeft;
    const y0 = defEl.offsetTop;
    const maxX = Math.max(8, innerWidth - defEl.offsetWidth - 12);
    const maxY = Math.max(8, innerHeight - defEl.offsetHeight - 8);
    const dx = x0 - e.clientX;
    const dy = y0 - e.clientY;
    let moved = false;
    const move = (ev) => {
      moved = true;
      defPos = { x: clamp(dx + ev.clientX, 8, maxX), y: clamp(dy + ev.clientY, 8, maxY) };
      defEl.style.transform = `translate(${defPos.x - x0}px, ${defPos.y - y0}px)`;
    };
    const up = () => {
      for (const t of ["pointermove", "pointerup", "pointercancel"]) defHead.removeEventListener(t, t === "pointermove" ? move : up);
      if (!moved) return;
      defEl.style.transform = "";
      defEl.style.left = `${defPos.x}px`;
      defEl.style.top = `${defPos.y}px`;
      defEl.style.right = "auto";
    };
    defHead.addEventListener("pointermove", move);
    defHead.addEventListener("pointerup", up);
    defHead.addEventListener("pointercancel", up);
  });
  defHead.addEventListener("dblclick", (e) => {
    if (e.target.closest("button, .path")) return;
    defPos = null;
    defEl.style.left = "";
    placeDef();
  });
  addEventListener("resize", () => placeDef());
  let defTurn = 0; // every open and close takes one, so a slow load cannot show over what came after it
  async function showDef(ids, k = 0, pt = null) {
    const m = defMeta[ids[k]];
    if (!m) return;
    const turn = ++defTurn;
    let src;
    try {
      src = await source(m[0]);
    } catch {
      return noSource();
    }
    if (turn !== defTurn) return;
    const [i, at, len, path, line] = m;
    defNow = { ids, k };
    const cut = path.lastIndexOf("/") + 1;
    const dir = document.createElement("span");
    dir.className = "dir";
    dir.textContent = path.slice(0, cut);
    const no = document.createElement("b");
    no.textContent = `:${line}`;
    $(".path", defEl).replaceChildren(dir, path.slice(cut), no);
    const u = document.createElement("div");
    u.className = "code u";
    u.dataset.src = i;
    u.dataset.at = at;
    u.append(makeRows(src, at, at + len, ""));
    if (traceOn) for (const t of u.querySelectorAll(`.tr[data-tr="${traceOn}"]`)) t.classList.add("on");
    defBody.replaceChildren(u);
    setup(u);
    $(".def-nav", defEl).hidden = ids.length < 2;
    $(".def-n", defEl).textContent = `${k + 1} of ${ids.length}`;
    defEl.hidden = false;
    defBody.scrollTop = 0;
    placeDef(pt);
  }
  function closeDef() {
    defTurn++;
    defEl.hidden = true;
    defBody.replaceChildren();
    defNow = null;
  }

  // ---------- story map ----------

  const side = $("#side");
  const map = $("#map");
  const chapters = $$("section[data-chapter]", main);
  const nodes = new Map();
  const branchNodes = new Map();
  {
    const ol = document.createElement("ol");
    ol.innerHTML = '<span class="rail"></span><span class="fill"></span>';
    let sep = false;
    const item = (title, sub) => {
      const li = document.createElement("li");
      li.innerHTML = '<button type="button"><span class="dot"><i></i></span><span class="txt"><span class="lbl"></span><span class="sub"></span></span><span class="cnt"></span></button>';
      $(".lbl", li).textContent = title;
      if (sub) $(".sub", li).textContent = sub;
      else $(".sub", li).remove();
      return li;
    };
    const closeDrawer = () => {
      if (!narrow.matches) return;
      body.classList.remove("side-open-m");
      applySide();
    };
    for (const ch of chapters) {
      if (ch.dataset.chapter === "appendix" && !sep) {
        const s = document.createElement("li");
        s.className = "sep";
        ol.append(s);
        sep = true;
      }
      const li = item(ch.dataset.title, ch.dataset.where);
      $("button", li).addEventListener("click", () => {
        goTo(ch, { glow: false });
        closeDrawer();
      });
      ol.append(li);
      nodes.set(ch, li);
      for (const br of $$(".branch-wrap", ch)) {
        const bl = item(br.dataset.title);
        bl.classList.add("branch");
        $("button", bl).addEventListener("click", () => {
          setBranch(br, true);
          const fork = forkOf(br);
          quiet(1400);
          setTimeout(() => (fork || br).scrollIntoView({ behavior: smooth(), block: "start" }), 30);
          closeDrawer();
        });
        ol.append(bl);
        branchNodes.set(br, bl);
      }
    }
    map.append(ol);
  }

  let active = null;
  // The map moves while the page scrolls, so its bars are scaled, never sized: a height or width in motion
  // lays the page out and repaints the story on every frame of the transition.
  const setBar = (part) => ($(".side-f .bar i").style.transform = `scaleX(${part})`);
  function placeFill() {
    const li = nodes.get(active);
    const fill = $(".fill", map);
    if (li && fill) fill.style.transform = `scaleY(${clamp((li.offsetTop + 4) / (fill.offsetHeight || 1), 0, 1)})`;
  }
  function spy() {
    const y = innerHeight * 0.36;
    let cur = chapters[0];
    for (const ch of chapters) if (ch.getBoundingClientRect().top <= y) cur = ch;
    // resting right on a boundary must not flip the map between two chapters
    const edge = active && chapters.indexOf(cur) > chapters.indexOf(active) ? cur : active;
    if (cur !== active && edge && Math.abs(edge.getBoundingClientRect().top - y) < 8) return;
    if (cur !== active) {
      active = cur;
      updateMap();
    }
  }
  function updateMap() {
    let passed = true;
    for (const [ch, li] of nodes) {
      if (ch === active) passed = false;
      li.classList.toggle("active", ch === active);
      li.classList.toggle("passed", passed);
    }
    for (const [br, li] of branchNodes) li.classList.toggle("open", br.classList.contains("open"));
    if (TOUR) {
      const numbered = chapters.filter((c) => c.dataset.chapter !== "appendix");
      const k = numbered.includes(active) ? numbered.indexOf(active) + 1 : numbered.length;
      setBar(k / (numbered.length || 1));
      $(".side-f .f-txt").textContent = `Chapter ${k} of ${numbered.length}`;
    }
    placeFill();
    const li = nodes.get(active);
    if (li && !side.matches(":hover")) {
      const sc = $(".side-scroll", side);
      const r = li.getBoundingClientRect();
      const b = sc.getBoundingClientRect();
      if (b.height && (r.top < b.top || r.bottom > b.bottom)) sc.scrollTo({ top: sc.scrollTop + r.top - b.top - b.height / 3, behavior: smooth() });
    }
  }

  // map panel: always floating. Open, or collapsed to a rail that still shows progress.
  // Dragged by its header, resized from any edge. At its home spot the story column makes room for it.
  const MAP_HOME = { x: 12, y: 76 };
  const MINI_W = 44;
  const MAP_W = 268;
  let mini = store.get("mapMini", false);
  let mapW = store.get("mapW", MAP_W);
  let mapH = store.get("mapH", null); // null: fits its content
  let mapPos = store.get("mapPos", null); // null: home
  const mapBtn = $('[data-act="map-mini"]', side);
  // at home the map shares the row with the story, so it never squeezes the column below 540px
  const homeMax = () => Math.min(560, Math.max(200, innerWidth - 632));
  const maxW = () => (mapPos ? Math.min(560, innerWidth - 16) : homeMax());
  const shownW = () => (mini ? MINI_W : Math.min(mapW, maxW()));
  function placeMap() {
    if (narrow.matches) {
      side.removeAttribute("style");
      return;
    }
    const w = shownW();
    const p = mapPos || MAP_HOME;
    const x = clamp(p.x, 8, innerWidth - w - 8);
    const y = clamp(p.y, 68, Math.max(68, innerHeight - 152));
    if (mapPos) mapPos = { x, y };
    side.classList.toggle("home", !mapPos);
    const room = innerHeight - y - 12;
    side.style.left = `${x}px`;
    side.style.top = `${y}px`;
    side.style.width = `${w}px`;
    side.style.maxHeight = `${room}px`;
    side.style.height = !mini && mapH ? `${Math.min(mapH, room)}px` : "";
    side.classList.toggle("sized", !mini && !!mapH);
    // away from home or resized: offer the way back, not just the double-click
    $('[data-act="map-home"]', side).hidden = !mapPos && !mapH && mapW === MAP_W;
    cacheSlot();
  }
  let mapMotion = null;
  let snapTimer = 0;
  function snapMap() {
    clearTimeout(snapTimer);
    side.classList.add("snap");
    snapTimer = setTimeout(() => side.classList.remove("snap"), 340);
  }
  let changingLane = false;
  function moveLane(fn) {
    cancelAnchor();
    const at = anchorFor();
    const top = at?.().getBoundingClientRect().top;
    const x = main.getBoundingClientRect().left + parseFloat(getComputedStyle(main).paddingLeft);
    mapMotion?.cancel();
    mapMotion = null;
    changingLane = true;
    fn();
    const room = colW() >= COL_MIN;
    if (room !== roomy) {
      roomy = room;
      applyView();
    }
    const dx = x - main.getBoundingClientRect().left - parseFloat(getComputedStyle(main).paddingLeft);
    if (at && at().getClientRects().length) {
      quiet(600);
      scrollTo({ top: scrollY + at().getBoundingClientRect().top - top, behavior: "instant" });
      // Scroll offsets round to device pixels; keep the subpixel remainder in the column,
      // folding whole pixels back into the scroll so the offset never accumulates.
      const remainder = top - at().getBoundingClientRect().top;
      if (Math.abs(remainder) < 1) {
        let y = (parseFloat(main.style.top) || 0) + remainder;
        const whole = Math.trunc(y);
        if (whole) scrollTo({ top: scrollY - whole, behavior: "instant" });
        y -= whole;
        main.style.top = y ? `${y}px` : "";
      }
    }
    changingLane = false;
    if (!reduced && Math.abs(dx) > 0.5) {
      // Reflow once; translating the finished layout keeps wrapping out of the animation frames.
      const sizing = side.getAnimations().find((a) => a.transitionProperty === "width");
      const motion = main.animate([{ transform: `translateX(${dx}px)` }, { transform: "none" }], {
        duration: sizing?.effect.getComputedTiming().duration || 300,
        easing: getComputedStyle(root).getPropertyValue("--ease").trim(),
      });
      mapMotion = motion;
      motion.onfinish = () => {
        if (mapMotion === motion) mapMotion = null;
      };
    }
    queueWires();
  }
  const laneW = () => (narrow.matches || mapPos ? 0 : shownW() + 12);
  let appliedLane = null;
  function applyLane() {
    const lane = laneW();
    if (lane === appliedLane) return;
    appliedLane = lane;
    main.style.paddingLeft = `calc(${lane}px + var(--gutter))`;
    pill.style.left = `calc(50% + ${lane / 2}px)`;
    queueWires();
  }
  function applySide() {
    if (narrow.matches) {
      body.classList.remove("map-mini");
      const open = body.classList.contains("side-open-m");
      side.inert = !open;
      $$('[data-act="side"]').forEach((b) => b.setAttribute("aria-pressed", String(open)));
    } else {
      side.inert = false;
      body.classList.toggle("map-mini", mini);
    }
    const m = mini && !narrow.matches;
    mapBtn.setAttribute("aria-expanded", String(!m));
    mapBtn.title = narrow.matches ? "Close the map" : m ? "Expand the map (m)" : "Collapse the map (m)";
    mapBtn.setAttribute("aria-label", mapBtn.title.replace(/ \(m\)$/, ""));
    // collapsed, the dots are all that's left of each chapter: name them for the pointer and screen readers
    for (const [ch, li] of nodes) {
      const b = $("button", li);
      if (m) b.setAttribute("aria-label", (b.title = ch.dataset.title));
      else b.removeAttribute("title"), b.removeAttribute("aria-label");
    }
    placeMap();
    applyLane();
  }
  function toggleSide() {
    if (narrow.matches) {
      body.classList.toggle("side-open-m");
      applySide();
      return;
    }
    mini = !mini;
    store.set("mapMini", mini);
    moveLane(applySide);
  }
  function resetMap() {
    snapMap();
    mapPos = null;
    mapH = null;
    mapW = MAP_W;
    ["mapPos", "mapH", "mapW"].forEach((k) => store.set(k, k === "mapW" ? MAP_W : null));
    moveLane(applySide);
  }
  // moving or resizing touches only the panel; the story column adjusts once, on release
  function settleMap() {
    store.set("mapPos", mapPos);
    store.set("mapW", mapW);
    store.set("mapH", mapH);
    cacheSlot();
    if (appliedLane !== laneW()) moveLane(applyLane);
  }
  narrow.addEventListener("change", () => {
    mapMotion?.cancel();
    mapMotion = null;
    applySide();
    applyView();
    cacheSlot();
  });
  addEventListener("resize", () => {
    if (!mapPos && !narrow.matches) moveLane(() => { placeMap(); applyLane(); });
    else placeMap();
  });

  function dragResize(handle, onMove, onEnd) {
    handle.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      handle.setPointerCapture(e.pointerId);
      body.classList.add("resizing");
      const move = (ev) => onMove(ev, e);
      const up = () => {
        body.classList.remove("resizing");
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", up);
        handle.removeEventListener("pointercancel", up);
        onEnd();
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", up);
      handle.addEventListener("pointercancel", up);
    });
  }
  for (const h of $$(".mr", side)) {
    const dir = h.dataset.dir;
    let r0 = null;
    h.addEventListener("pointerdown", () => (r0 = side.getBoundingClientRect()), true);
    dragResize(
      h,
      (ev, down) => {
        const dx = ev.clientX - down.clientX;
        const dy = ev.clientY - down.clientY;
        let { left: x, top: y, width: w, height: hh } = r0;
        if (dir.includes("e")) w = r0.width + dx;
        if (dir.includes("w")) w = r0.width - dx;
        if (dir.includes("s")) hh = r0.height + dy;
        if (dir.includes("n")) hh = r0.height - dy;
        w = clamp(w, 200, maxW());
        hh = clamp(hh, 140, innerHeight - 16);
        if (dir.includes("w")) x = r0.right - w;
        if (dir.includes("n")) y = r0.bottom - hh;
        mapW = Math.round(w);
        if (dir.includes("n") || dir.includes("s")) mapH = Math.round(hh);
        if (mapPos) mapPos = { x: Math.round(x), y: Math.round(y) };
        placeMap();
      },
      settleMap,
    );
  }
  // keyboard: the right edge resizes the width, the bottom edge the height
  for (const h of $$('.mr[tabindex="0"]', side))
    h.addEventListener("keydown", (e) => {
      const horiz = h.dataset.dir === "e";
      const keys = horiz ? ["ArrowLeft", "ArrowRight"] : ["ArrowUp", "ArrowDown"];
      if (!keys.includes(e.key)) return;
      e.preventDefault();
      const d = e.key === keys[0] ? -20 : 20;
      if (horiz) mapW = clamp(Math.min(mapW, maxW()) + d, 200, maxW());
      else mapH = clamp((mapH || side.offsetHeight) + d, 140, innerHeight - 16);
      placeMap();
      settleMap();
    });

  const sideH = $(".side-h", side);
  const SNAP = 48;
  let slotSize = { width: `${MAP_W}px`, height: "140px" };
  let slotKey = "";
  let slotTask = 0;
  function cacheSlot() {
    if (body.classList.contains("resizing")) return;
    if (narrow.matches) {
      clearTimeout(slotTask);
      slotKey = "";
      return;
    }
    const w = mini ? MINI_W : Math.min(mapW, homeMax());
    const room = innerHeight - MAP_HOME.y - 12;
    const showHome = !!mapH || mapW !== MAP_W;
    const key = `${w}:${mapH}:${room}:${mini}:${showHome}`;
    if (key === slotKey) return;
    slotKey = key;
    clearTimeout(slotTask);
    // Measure a small, isolated copy between gestures, never in the first pointermove.
    slotTask = setTimeout(() => {
      const copy = side.cloneNode(true);
      copy.removeAttribute("id");
      $$("[id]", copy).forEach((el) => el.removeAttribute("id"));
      copy.inert = true;
      copy.setAttribute("aria-hidden", "true");
      copy.classList.remove("snap");
      copy.classList.add("home");
      $('[data-act="map-home"]', copy).hidden = !showHome;
      Object.assign(copy.style, { left: "-2000px", top: "0", width: `${w}px`, maxHeight: `${room}px`, height: !mini && mapH ? `${Math.min(mapH, room)}px` : "", visibility: "hidden", transition: "none" });
      body.append(copy);
      slotSize = { width: `${w}px`, height: `${copy.offsetHeight}px` };
      copy.remove();
    }, 0);
  }
  if ("ResizeObserver" in window) new ResizeObserver(cacheSlot).observe(side);
  // content changes (trace counters) can rewrap the map without changing the cache key
  new MutationObserver(() => {
    slotKey = "";
    cacheSlot();
  }).observe(side, { childList: true, characterData: true, subtree: true });
  const slot = document.createElement("div");
  slot.className = "map-slot";
  slot.setAttribute("aria-hidden", "true");
  body.append(slot);
  sideH.addEventListener("pointerdown", (e) => {
    if (narrow.matches || e.button !== 0 || e.target.closest("button")) return;
    e.preventDefault();
    const r = side.getBoundingClientRect();
    const dx = e.clientX - r.left;
    const dy = e.clientY - r.top;
    sideH.setPointerCapture(e.pointerId);
    body.classList.add("dragging");
    // the home slot shows while dragging, so docking on release is expected, not a surprise
    const near = () => mapPos && Math.abs(mapPos.x - MAP_HOME.x) < SNAP && Math.abs(mapPos.y - MAP_HOME.y) < SNAP;
    let moved = false;
    const move = (ev) => {
      side.classList.remove("snap");
      mapPos = { x: Math.round(ev.clientX - dx), y: Math.round(ev.clientY - dy) };
      placeMap();
      if (!moved) {
        moved = true;
        Object.assign(slot.style, slotSize);
        slot.classList.add("on");
      }
      slot.classList.toggle("near", !!near());
    };
    const up = () => {
      body.classList.remove("dragging");
      sideH.removeEventListener("pointermove", move);
      sideH.removeEventListener("pointerup", up);
      slot.classList.remove("on", "near");
      if (!moved) return;
      if (near()) {
        mapPos = null;
        snapMap();
        placeMap();
      }
      settleMap();
    };
    sideH.addEventListener("pointermove", move);
    sideH.addEventListener("pointerup", up);
  });
  sideH.addEventListener("dblclick", (e) => !e.target.closest("button") && !narrow.matches && resetMap());

  let ticking = false;
  addEventListener(
    "scroll",
    () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        ticking = false;
        spy();
        onScrollHdr();
      });
    },
    { passive: true },
  );

  // ---------- reviewed ----------

  // keyed by the frame's content too, so a frame whose code changed since it was marked comes back unreviewed
  // content, not position: inserting a frame mustn't drop the marks after it
  const rkey = (f) => `${f.dataset.path || f.id}:${f.dataset.hash || ""}`;
  const isReviewed = (f) => reviewed.has(rkey(f));
  const reviewed = new Set(store.get("reviewed", []).filter((k) => diffFrames.some((f) => rkey(f) === k)));
  function refreshReviewed() {
    if (TOUR) return;
    for (const f of diffFrames) {
      const on = isReviewed(f);
      f.classList.toggle("reviewed", on);
      const b = $('.fh [data-act="reviewed"]', f);
      if (b) {
        b.setAttribute("aria-pressed", String(on));
        b.title = on ? "Reviewed: click to undo" : "Mark reviewed (r)";
      }
    }
    const done = diffFrames.filter(isReviewed).length;
    const n = diffFrames.length;
    const bar = $(".progress .pbar");
    const c = 2 * Math.PI * 8.5;
    bar.style.strokeDasharray = c;
    bar.style.strokeDashoffset = c * (1 - done / (n || 1));
    $(".progress .p-txt").textContent = `${done}/${n} reviewed`;
    $(".progress").title = `${done} of ${n} changed frames reviewed`;
    setBar(done / (n || 1));
    $(".side-f .f-txt").textContent = `${done} of ${n} frames reviewed`;
    for (const [ch, li] of nodes) {
      const own = diffFrames.filter((f) => ch.contains(f));
      li.classList.toggle("done", own.length > 0 && own.every(isReviewed));
    }
  }
  function toggleReviewed(f) {
    isReviewed(f) ? reviewed.delete(rkey(f)) : reviewed.add(rkey(f));
    store.set("reviewed", [...reviewed]);
    refreshReviewed();
    setFrame(f, isReviewed(f));
  }

  // ---------- frames fold to their header ----------

  function setFrame(f, collapsed, settle = true) {
    if (f.classList.contains("collapsed") === collapsed) return;
    f.classList.toggle("collapsed", collapsed);
    const b = $(":scope > .fh > .fh-tog", f);
    b.setAttribute("aria-expanded", String(!collapsed));
    b.setAttribute("aria-label", collapsed ? "Expand" : "Collapse");
    // folded from the keyboard, the header can be off screen above the code that just went: bring it back
    const top = settle && collapsed && f.getClientRects().length ? f.getBoundingClientRect().top : Infinity;
    if (top < 64) {
      cancelAnchor();
      quiet(600);
      scrollTo({ top: scrollY + top - 90, behavior: "instant" });
    }
    queueWires();
  }

  // ---------- trees: a listed file that a frame shows jumps there ----------

  for (const row of $$(".trow", main)) {
    const p = CSS.escape(row.dataset.path);
    const target = $(`figure.frame:not(.tree)[data-path="${p}"], details.file-item[data-path="${p}"]`, main);
    if (!target) continue;
    row.classList.add("hit");
    row.title = "Shown in the story; click to go there";
    row.tabIndex = 0;
    row.setAttribute("role", "link");
    row.addEventListener("click", () => goTo(target));
    row.addEventListener("keydown", (e) => e.key === "Enter" && goTo(target));
  }

  // ---------- notes ----------

  let notesOff = store.get("notesOff", false);
  function applyNotes() {
    body.classList.toggle("notes-off", notesOff);
    $$('[data-act="notes"]').forEach((b) => b.setAttribute("aria-pressed", String(!notesOff)));
    // an attachment that only held a review note has nothing left to show
    $$(".attach").forEach((a) => {
      const onlyNote = !$("figure.frame", a) && $(".note.review", a);
      a.hidden = !!(onlyNote && notesOff);
    });
    queueWires();
  }
  function toggleNotes() {
    notesOff = !notesOff;
    store.set("notesOff", notesOff);
    keepAnchor(applyNotes, 120);
  }

  // ---------- branches, opened in place ----------

  const forkOf = (br) => $(`[data-act="branch"][aria-controls="${br.id}"]`)?.closest(".fork");
  function setBranch(br, open, { instant = false } = {}) {
    if (open) {
      const fork = forkOf(br);
      // one branch per fork at a time
      if (fork)
        $$('[data-act="branch"]', fork).forEach((b) => {
          const o = document.getElementById(b.getAttribute("aria-controls"));
          if (o && o !== br && o.classList.contains("open")) setBranch(o, false, { instant: true });
        });
    }
    if (instant) {
      br.style.transition = "none";
      $(".branch-in", br).style.transition = "none";
    }
    br.classList.toggle("open", open);
    br.inert = !open;
    $$(`[data-act="branch"][aria-controls="${br.id}"]`).forEach((b) => b.setAttribute("aria-expanded", String(open)));
    if (instant) {
      void br.offsetHeight;
      br.style.transition = "";
      $(".branch-in", br).style.transition = "";
    }
    updateMap();
    queueWires();
  }
  $$(".branch-wrap").forEach((br) => br.addEventListener("transitionend", queueWires));

  // ---------- trace ----------

  const pop = $("#trace-pop");
  const pill = $(".tracepill");
  const traceBtn = $('[data-act="trace-menu"]');
  let traceOn = null;
  let lit = [];
  let traceIdx = -1;
  const traceable = (x) => main.contains(x) && !x.closest(".nis-group");
  const traceSpans = (g) => $$(`.tr[data-tr="${g}"]`, main).filter(traceable);
  const holder = (x) => x.closest("figure.frame, .file-item");

  function setTrace(g, origin) {
    traceOn = g;
    lit = [];
    traceIdx = -1;
    $$(".tr.on").forEach((x) => x.classList.remove("on"));
    $$(".lit").forEach((x) => x.classList.remove("lit", "current"));
    for (const li of nodes.values()) {
      li.classList.remove("hot");
      li.style.removeProperty("--heat");
      $(".cnt", li).textContent = "";
    }
    body.classList.toggle("tracing", !!g);
    pill.inert = !g;
    traceBtn.classList.toggle("tracing", !!g);
    $(".tname", traceBtn).textContent = g ? traceNames[g] || g : "Trace";
    $$("#trace-pop button[data-tr]").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.tr === g)));
    $('#trace-pop [data-act="trace-clear"]').hidden = !g;
    if (!g) return;
    const spans = traceSpans(g);
    spans.forEach((x) => x.classList.add("on"));
    for (const x of $$(`.tr[data-tr="${g}"]`, defEl)) x.classList.add("on");
    lit = [...new Set(spans.map(holder).filter(Boolean))];
    lit.forEach((f) => f.classList.add("lit"));
    const counts = new Map();
    for (const f of lit) {
      const ch = f.closest("section[data-chapter]");
      counts.set(ch, (counts.get(ch) || 0) + 1);
    }
    const max = Math.max(1, ...counts.values());
    for (const [ch, c] of counts) {
      const li = nodes.get(ch);
      if (!li) continue;
      li.classList.add("hot");
      li.style.setProperty("--heat", (0.35 + (0.65 * c) / max).toFixed(2));
      $(".cnt", li).textContent = c;
    }
    $(".tp-name").textContent = traceNames[g] || g;
    traceIdx = origin ? lit.indexOf(holder(origin)) : -1;
    if (traceIdx >= 0) lit[traceIdx].classList.add("current");
    showTraceAt();
  }
  // where the reader stands among the frames a trace lights: "4 / 16" once one of them is current
  function showTraceAt() {
    const n = lit.length;
    const c = $(".tp-count");
    c.textContent = traceIdx >= 0 ? `${traceIdx + 1} / ${n}` : `${n} ${n === 1 ? "frame" : "frames"}`;
    c.title = traceIdx >= 0 ? `Frame ${traceIdx + 1} of ${n} that show it` : "";
  }
  function stepTrace(d) {
    if (!traceOn || !lit.length) return;
    if (traceIdx >= 0) lit[traceIdx].classList.remove("current");
    traceIdx = (traceIdx + d + lit.length) % lit.length;
    const f = lit[traceIdx];
    f.classList.add("current");
    showTraceAt();
    reveal(f);
    if (f.matches("figure.frame")) setFrame(f, false);
    quiet(1200);
    requestAnimationFrame(() => f.scrollIntoView({ behavior: smooth(), block: "center" }));
  }
  {
    for (const [g, name] of Object.entries(traceNames)) {
      const n = new Set(traceSpans(g).map(holder).filter(Boolean)).size;
      if (!n) continue;
      const b = document.createElement("button");
      b.type = "button";
      b.className = "item";
      b.setAttribute("role", "menuitemradio");
      b.setAttribute("aria-checked", "false");
      b.dataset.tr = g;
      b.innerHTML = '<span class="nm"></span><span class="meta"></span>';
      $(".nm", b).textContent = name;
      $(".meta", b).textContent = `${n} ${n === 1 ? "frame" : "frames"}`;
      pop.append(b);
    }
    const sep = document.createElement("div");
    sep.className = "sep";
    sep.setAttribute("role", "separator");
    const stop = document.createElement("button");
    stop.type = "button";
    stop.className = "item";
    stop.dataset.act = "trace-clear";
    stop.setAttribute("role", "menuitem");
    stop.innerHTML = 'Stop tracing<span class="meta">esc</span>';
    stop.hidden = true;
    pop.append(sep, stop);
  }
  const HDR_EDGE = 12 + 48 + 8;
  function placePop() {
    // from the header's resting place: it may still be sliding in
    const r = traceBtn.getBoundingClientRect();
    const atBottom = r.top + r.height / 2 > innerHeight / 2;
    pop.style.top = atBottom ? "auto" : `${HDR_EDGE}px`;
    pop.style.bottom = atBottom ? `${HDR_EDGE}px` : "auto";
    pop.style.maxHeight = `${innerHeight - HDR_EDGE - 16}px`;
    pop.style.left = `${clamp(r.left, 8, innerWidth - pop.offsetWidth - 8)}px`;
  }
  const popItems = () => $$("button.item", pop).filter((b) => !b.hidden);
  function setPop(open, { focus = false } = {}) {
    pop.hidden = !open;
    traceBtn.setAttribute("aria-expanded", String(open));
    if (open) {
      setHdr(false);
      placePop();
      if (focus) (popItems().find((b) => b.getAttribute("aria-checked") === "true") || popItems()[0])?.focus();
    }
  }
  pop.addEventListener("keydown", (e) => {
    const items = popItems();
    const i = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length].focus();
    } else if (e.key === "Escape" || e.key === "Tab") {
      if (e.key === "Escape") e.preventDefault();
      setPop(false);
      traceBtn.focus();
      e.stopPropagation();
    }
  });
  addEventListener("resize", () => !pop.hidden && placePop());

  // ---------- modal overlays: full diff and shortcuts ----------

  // open dialogs, topmost last; everything under the top one is inert
  const modals = [];
  function syncModals() {
    const any = modals.length > 0;
    for (const el of [app, ...$$(".hdr"), pop]) el.inert = any;
    defEl.inert = modals.some((m) => m.el.id === "help"); // it stays in use over the full diff
    pill.inert = any || !traceOn;
    modals.forEach((m, i) => (m.el.inert = i < modals.length - 1));
  }
  function openModal(el, focusEl) {
    if (modals.some((m) => m.el === el)) return;
    modals.push({ el, focusEl, back: document.activeElement });
    setPop(false);
    syncModals();
    focusEl.focus({ preventScroll: true });
  }
  function closeModal(el) {
    const i = modals.findIndex((m) => m.el === el);
    if (i < 0) return;
    const [m] = modals.splice(i, 1);
    syncModals();
    const back = m.back && document.contains(m.back) && !m.back.closest("[inert]") ? m.back : modals.at(-1)?.focusEl;
    back?.focus({ preventScroll: true });
  }
  const help = $("#help");
  function setHelp(open) {
    help.hidden = !open;
    open ? openModal(help, $(".sheet-in", help)) : closeModal(help);
  }

  const files = $("#files");
  const fdBody = $(".files-body", files);
  const fdMain = $(".files-main", files);
  if ("ResizeObserver" in window)
    new ResizeObserver(() => {
      if (files.hidden) return;
      const r = fdBody.clientWidth >= SPLIT_MIN;
      if (r === fdRoomy) return;
      fdRoomy = r;
      keepFdAnchor(applyView);
    }).observe(fdBody);
  // the anchor is taken before the width changes: rewrapping everything above it moves it too
  function setFdNav(w) {
    keepFdAnchor(() => {
      fdNavW = w;
      fdMain.style.setProperty("--fd-nav-w", `${w}px`);
      const r = fdBody.clientWidth >= SPLIT_MIN;
      if (r !== fdRoomy) {
        fdRoomy = r;
        applyView();
      }
    });
  }
  // same as keepAnchor, inside the overlay's own scroller
  function keepFdAnchor(fn) {
    const box = fdBody.getBoundingClientRect();
    let row = null;
    for (const y of [80, 160, 260, 400]) {
      const el = document.elementFromPoint(box.left + 120, box.top + y);
      const r = el && el.closest("#files .row, #files .srow");
      if (!r) continue;
      const x = r.matches(".srow") ? r._R || r._L : r;
      if (!row) row = x;
      if (x.dataset.o && x.dataset.n) {
        row = x;
        break;
      }
    }
    const at = row && (() => shown(row));
    const t0 = at ? at().getBoundingClientRect().top : 0;
    fn();
    if (at) fdBody.scrollTop += at().getBoundingClientRect().top - t0;
  }
  let fdNavW = store.get("fdNavW", 300);
  fdMain.style.setProperty("--fd-nav-w", `${fdNavW}px`);
  function scrollFd(el, pad = 12) {
    fdBody.scrollTop += el.getBoundingClientRect().top - fdBody.getBoundingClientRect().top - pad;
  }
  async function openFiles(frame, target) {
    if (files.hidden) {
      files.hidden = false;
      body.classList.add("files-open");
      openModal(files, $(".traffic", files));
    }
    fdRoomy = fdBody.clientWidth >= SPLIT_MIN;
    applyView();
    if (!target && frame) target = document.getElementById(frame.dataset.fd || "");
    if (target) {
      const file = target.closest(".fd-file");
      if (file) setFdFile(file, false);
      await fillIn(file || target);
      scrollFd(vis(target), 60);
      flash(vis(target));
    }
    fdSpy();
    fdFill();
  }
  // the full diff's rows come in a file at a time: whatever is near the screen at once, the rest in the
  // background, so opening it never waits on the whole diff and searching the page soon finds all of it
  const fdLazy = $$(".code.u[data-src]", files);
  const ROW_H = 21.5;
  for (const u of fdLazy) u.style.minHeight = `${ROW_H * $$("[data-len]", u).reduce((n, g) => n + +g.dataset.len, 0)}px`;
  let fdTimer = 0;
  let fdTodo = fdLazy;
  function fdFill() {
    clearTimeout(fdTimer);
    fdTodo = fdTodo.filter((u) => !u._ready);
    if (!fdTodo.length || files.hidden) return;
    const box = fdBody.getBoundingClientRect();
    const near = fdTodo.filter((u) => {
      const r = u.getBoundingClientRect();
      return r.height && r.bottom > box.top - box.height && r.top < box.bottom + box.height;
    });
    (near.length ? near : fdTodo.slice(0, 1)).forEach(ready);
    fdTimer = setTimeout(fdFill, 40);
  }
  function closeFiles() {
    if (files.hidden) return;
    files.hidden = true;
    body.classList.remove("files-open");
    closeModal(files);
  }
  function setFdFile(file, collapsed, sync = true) {
    file.classList.toggle("collapsed", collapsed);
    const b = $(".fd-tog", file);
    b.setAttribute("aria-expanded", String(!collapsed));
    b.setAttribute("aria-label", collapsed ? "Expand file" : "Collapse file");
    if (sync) syncFdAll(), fdFill();
  }
  function syncFdAll() {
    const anyOpen = $$(".fd-file", files).some((f) => !f.classList.contains("collapsed"));
    $('[data-act="fd-all"]', files).textContent = anyOpen ? "Collapse all" : "Expand all";
  }
  const fdFiles = $$(".fd-file", files);
  const fdLinks = new Map($$(".files-nav a", files).map((a) => [a.dataset.fd, a]));
  let fdCur = null;
  function fdSpy() {
    const top = fdBody.getBoundingClientRect().top + 40;
    let cur = fdFiles[0];
    for (const f of fdFiles) {
      if (f.getBoundingClientRect().top > top) break;
      cur = f;
    }
    if (cur === fdCur) return;
    const was = fdCur && fdLinks.get(fdCur.id);
    if (was) was.classList.remove("cur"), was.removeAttribute("aria-current");
    fdCur = cur;
    const a = cur && fdLinks.get(cur.id);
    if (a) a.classList.add("cur"), a.setAttribute("aria-current", "true");
  }
  let fdTick = false;
  fdBody.addEventListener(
    "scroll",
    () => {
      if (fdTick) return;
      fdTick = true;
      requestAnimationFrame(() => {
        fdTick = false;
        fdSpy();
        fdFill();
      });
    },
    { passive: true },
  );
  const fdHandle = $(".files-resize", files);
  dragResize(
    fdHandle,
    (e) => {
      setFdNav(clamp(Math.round(e.clientX - fdMain.getBoundingClientRect().left - 3), 180, 560));
    },
    () => store.set("fdNavW", fdNavW),
  );
  fdHandle.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    setFdNav(clamp(fdNavW + (e.key === "ArrowLeft" ? -20 : 20), 180, 560));
    store.set("fdNavW", fdNavW);
  });
  // name each way back into the story by where it lands
  for (const b of $$(".fd-back", files)) {
    const el = document.getElementById(b.dataset.goto);
    const where = el && (el.closest("[data-branch]") || el.closest("section[data-chapter]"));
    if (where) b.textContent = `Show in ${where.dataset.title}`;
  }

  function frameNearCenter() {
    const y = innerHeight / 2;
    let best = null;
    let bd = Infinity;
    for (const f of diffFrames) {
      const r = f.getBoundingClientRect();
      if (!r.height) continue;
      const d = r.top <= y && r.bottom >= y ? 0 : Math.min(Math.abs(r.top - y), Math.abs(r.bottom - y));
      if (d < bd) {
        bd = d;
        best = f;
      }
    }
    return best;
  }

  // ---------- rows: GitHub link, selection, links to attachments ----------

  for (const s of $$(".fh .sym", main)) if (s.textContent) s.title = s.textContent;

  const gh = document.createElement("a");
  gh.className = "ghjump";
  gh.target = "_blank";
  gh.rel = "noopener";
  gh.setAttribute("aria-label", "Open this line on GitHub");
  function ghHref(line) {
    const host = line.closest("[data-gh], [data-blob]");
    if (!host) return null;
    if (host.dataset.blob) return `${host.dataset.blob}#L${line.dataset.n || line.dataset.line}`;
    if (line.classList.contains("half")) return line.dataset.line ? `${host.dataset.gh}${line.dataset.side}${line.dataset.line}` : null;
    if (line.dataset.n) return `${host.dataset.gh}R${line.dataset.n}`;
    if (line.dataset.o) return `${host.dataset.gh}L${line.dataset.o}`;
    return null;
  }
  function putGh(line) {
    const href = line && !line.classList.contains("e") && ghHref(line);
    if (!href) return gh.remove();
    gh.href = href;
    gh.title = `Open line ${line.dataset.n || line.dataset.o || line.dataset.line} on GitHub`;
    if (gh.parentElement !== line) line.prepend(gh);
  }
  // Hover on code is set here, not by :hover. The browser also hovers whatever scrolls under a resting
  // pointer, which lit and repainted a row on every frame of a scroll; while one runs, the last target waits.
  let hov = null;
  let hovNext = null;
  let scrollT = 0;
  function hover(el) {
    const line = el.closest(".row, .half");
    if (line !== hov) {
      hov?.classList.remove("hov");
      hov = line;
      line?.classList.add("hov");
    }
    if (line && !narrow.matches) putGh(line);
    onHoverLinks(el);
  }
  document.addEventListener("mouseover", (e) => (scrollT ? (hovNext = e.target) : hover(e.target)));
  root.addEventListener("mouseleave", () => hover(root));
  addEventListener(
    "scroll",
    () => {
      clearTimeout(scrollT);
      scrollT = setTimeout(() => {
        scrollT = 0;
        if (hovNext?.isConnected) hover(hovNext);
        hovNext = null;
      }, 100);
    },
    { passive: true, capture: true },
  );

  // a selection belongs to a host: a story frame, an appendix file or a full-diff hunk
  const HOST = "figure.frame, details.file-item, .fd-file";
  const hostRows = (host) => $$(".code.u .row", host).filter((r) => r.closest(HOST) === host);
  let sel = { host: null, rows: [], side: null };
  let anchor = null;
  function rowOf(el) {
    const h = el.closest(".half");
    if (h) {
      const s = h.parentElement;
      return h.dataset.side === "L" ? s._L || s._R : s._R || s._L;
    }
    return el.closest(".row");
  }
  const sideOf = (el) => el.closest(".half")?.dataset.side || null;
  const lineKey = (r, side) =>
    (side === "L" && r.dataset.o) || !r.dataset.n ? `L${r.dataset.o}` : `R${r.dataset.n}`;
  const inSplit = (r) => r._s && !r._s.parentElement.hidden;
  // what shows a row in the current view: itself, or in split its half (context rows: the clicked half or both)
  const shown = (r, side) => (!inSplit(r) ? r : r._h || (side === "L" ? r._hL : side === "R" ? r._hR : r._s));
  // contiguous runs of the selection, in the host's row order: "R15-R18,R21"
  const onSide = (r, side) => (side === "L" ? !!r.dataset.o : side === "R" ? !!r.dataset.n : true);
  function runs(host, rows, side) {
    const all = hostRows(host).filter((r) => onSide(r, side));
    const place = new Map(all.map((r, i) => [r, i]));
    const idx = rows.filter((r) => onSide(r, side)).map((r) => place.get(r)).sort((a, b) => a - b);
    const out = [];
    for (const i of idx) {
      const last = out[out.length - 1];
      if (last && i === last[1] + 1) last[1] = i;
      else out.push([i, i]);
    }
    return out.map(([a, b]) => lineKey(all[a], side) + (b > a ? `-${lineKey(all[b], side)}` : "")).join(",");
  }
  function select(host, rows, { scroll = false, hash = true, side = null } = {}) {
    const picked = new Set(rows);
    if (host) rows = hostRows(host).filter((r) => picked.has(r) && (!inSplit(r) || onSide(r, side)));
    sel = { host, rows, side };
    paintRows();
    if (hash)
      history.replaceState(null, "", rows.length ? `#${host.id}-${runs(host, rows, side)}` : location.pathname + location.search);
    if (narrow.matches) putGh(rows.length ? shown(rows[0], side) : null);
    if (scroll && rows.length) {
      reveal(rows[0]);
      quiet(1200);
      requestAnimationFrame(() => shown(rows[0], side).scrollIntoView({ behavior: smooth(), block: "center" }));
    }
  }
  async function readHash() {
    const m = /^#(.+?)-([LR]\d+(?:-[LR]\d+)?(?:,[LR]\d+(?:-[LR]\d+)?)*)$/.exec(decodeURIComponent(location.hash));
    if (!m) return;
    // a full-diff link made before files became one host names a hunk inside it
    const host = document.getElementById(m[1])?.closest(HOST);
    if (!host) return;
    if (files.contains(host)) await openFiles(null, host);
    else await fillIn(host);
    let rows = hostRows(host);
    const find = (k) => rows.findIndex((r) => (k[0] === "L" ? r.dataset.o : r.dataset.n) === k.slice(1));
    for (const part of m[2].split(",")) {
      const ends = part.split("-");
      if (ends.every((k) => find(k) >= 0)) continue;
      await expose(host, ends);
      rows = hostRows(host);
    }
    const keys = m[2].split(/[,-]/);
    const picked = [];
    for (const part of m[2].split(",")) {
      const [p, q = p] = part.split("-");
      const a = find(p);
      const b = find(q);
      if (a < 0 || b < 0) return;
      picked.push(...rows.slice(Math.min(a, b), Math.max(a, b) + 1));
    }
    // one prefix means one side (split paints only that side); a mixed selection came from unified
    const side = keys.every((k) => k[0] === keys[0][0]) ? keys[0][0] : null;
    select(host, picked, { scroll: true, hash: false, side });
    anchor = picked[picked.length - 1];
  }

  // attachments: data-lines="15" | "15,21" | "99-122", on the target frame's new-side numbers
  const attaches = $$(".attach[data-to]", main);
  const ranges = (att) =>
    (att.dataset.lines || "")
      .split(",")
      .filter(Boolean)
      .map((p) => p.split("-").map(Number))
      .map(([a, b]) => [a, b || a]);
  attaches.forEach((a, i) => (a.dataset.k = `w${i}`));
  for (const att of attaches) {
    const frame = document.getElementById(att.dataset.to);
    const rs = ranges(att);
    att._rows = frame
      ? hostRows(frame).filter((r) => {
          const n = Number(r.dataset.n);
          return n && rs.some(([a, b]) => n >= a && n <= b);
        })
      : [];
    for (const r of att._rows) {
      (r._att || (r._att = [])).push(att);
      r.classList.add("has-link");
    }
    const why = $(".why", att);
    const label = rs.map(([a, b]) => (a === b ? `L${a}` : `L${a}–${b}`)).join(", ");
    $(".to", att).textContent = label;
    why.tabIndex = 0;
    why.setAttribute("role", "button");
    why.title = `Show ${label} of ${frame?.dataset.path || "the code"}`;
  }
  let hoverAtt = new Set();
  function onHoverLinks(el) {
    const next = new Set();
    const att = el.closest(".attach");
    if (att) next.add(att);
    const line = !att && el.closest(".row, .half");
    const r = line && rowOf(line);
    if (r && r._att) r._att.forEach((a) => next.add(a));
    if (next.size === hoverAtt.size && [...next].every((a) => hoverAtt.has(a))) return;
    hoverAtt = next;
    paintRows();
  }
  function paintRows() {
    const on = new Set(hoverAtt);
    for (const r of sel.rows) if (r._att) r._att.forEach((a) => on.add(a));
    // a selected line inside a card keeps that card's link lit
    const inCard = sel.rows.length && sel.host.closest(".attach[data-to]");
    if (inCard) on.add(inCard);
    $$(".sel, .linked").forEach((x) => x.classList.remove("sel", "linked"));
    for (const r of sel.rows) {
      r.classList.add("sel");
      if (!r._s || (sel.side === "L" && !r.dataset.o) || (sel.side === "R" && !r.dataset.n)) continue;
      (r._h || (sel.side === "L" ? r._hL : sel.side === "R" ? r._hR : r._s)).classList.add("sel");
    }
    for (const a of on) {
      a.classList.add("linked");
      for (const r of a._rows) {
        r.classList.add("linked");
        if (r._s) (r._h || r._s).classList.add("linked");
      }
    }
    for (const a of on) $$(`svg.wires [data-for="${a.dataset.k}"]`).forEach((x) => x.classList.add("linked"));
  }
  function showAttach(att) {
    if (!att._rows.length) return;
    const frame = document.getElementById(att.dataset.to);
    const el = shown(att._rows[0]);
    const b = el.getBoundingClientRect();
    select(frame, att._rows, { scroll: !(b.top > 70 && b.bottom < innerHeight - 20) });
  }

  // ---------- wires ----------

  let wireQueued = false;
  function queueWires() {
    if (wireQueued || changingLane) return;
    wireQueued = true;
    requestAnimationFrame(() => {
      wireQueued = false;
      drawWires();
    });
  }
  const svgEl = (tag, attrs) => {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    return el;
  };
  function drawWires() {
    const drawings = [];
    const scale = main.getBoundingClientRect().width / main.offsetWidth;
    for (const step of $$(".step", main)) {
      const drawing = { step, marks: [], width: 0, height: 0 };
      drawings.push(drawing);
      const stacked = getComputedStyle(step).gridTemplateColumns.split(" ").length < 2;
      if (stacked || !step.offsetParent) continue;
      const sb = step.getBoundingClientRect();
      drawing.width = sb.width / scale;
      drawing.height = sb.height;
      for (const att of $$(".attach[data-to]", step)) {
        const frame = document.getElementById(att.dataset.to);
        if (att.hidden || !frame || frame.classList.contains("collapsed")) continue;
        const fb = frame.getBoundingClientRect();
        const wb = $(".why", att).getBoundingClientRect();
        const y2 = wb.top + 10 - sb.top;
        const x2 = (att.getBoundingClientRect().left - sb.left) / scale - 10;
        const x1 = (fb.right - sb.left) / scale;
        for (const [a, b] of ranges(att)) {
          const rs = att._rows.filter((r) => +r.dataset.n >= a && +r.dataset.n <= b).map(shown);
          if (!rs.length) continue;
          const y1 = (rs[0].getBoundingClientRect().top + rs[rs.length - 1].getBoundingClientRect().bottom) / 2 - sb.top;
          const mx = x1 + (x2 - x1) * 0.5;
          drawing.marks.push(svgEl("path", { d: `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`, "data-for": att.dataset.k }));
          drawing.marks.push(svgEl("circle", { cx: x1, cy: y1, r: 2.25, "data-for": att.dataset.k }));
        }
        drawing.marks.push(svgEl("circle", { cx: x2, cy: y2, r: 2.25, "data-for": att.dataset.k }));
      }
    }
    for (const { step, marks, width, height } of drawings) {
      let svg = step.querySelector(":scope > svg.wires");
      if (!svg) {
        svg = svgEl("svg", { class: "wires", "aria-hidden": "true" });
        step.prepend(svg);
      }
      svg.setAttribute("width", width);
      svg.setAttribute("height", height);
      svg.replaceChildren(...marks);
    }
    paintRows();
  }
  addEventListener("resize", queueWires);
  document.addEventListener(
    "toggle",
    (e) => {
      if (e.target.open) fillIn(e.target);
      queueWires();
    },
    true,
  );
  if ("ResizeObserver" in window)
    new ResizeObserver(() => {
      queueWires();
      const r = colW() >= COL_MIN;
      if (r === roomy) return;
      roomy = r;
      view === "split" ? keepAnchor(applyView, 120) : applyView();
    }).observe(main);

  // ---------- events ----------

  // shift-click extends a line selection instead of selecting text
  document.addEventListener("mousedown", (e) => {
    if (e.shiftKey && e.target.closest(".code .row, .code .srow")) e.preventDefault();
    const s = sideOf(e.target);
    body.classList.toggle("pick-L", s === "L");
    body.classList.toggle("pick-R", s === "R");
  });

  // drag down the line numbers to select a range, like GitHub; cmd/ctrl keeps what was selected
  let dragged = false;
  document.addEventListener("pointerdown", (e) => {
    dragged = false;
    if (e.button !== 0 || e.shiftKey || narrow.matches) return;
    const gut = e.target.closest(".code .row > .ln, .code .row > .sg, .code .half > .ln, .code .half > .sg");
    const host = gut && gut.closest(HOST);
    const start = gut && rowOf(gut);
    if (!host || !start || !hostRows(host).includes(start)) return;
    e.preventDefault();
    getSelection().removeAllRanges();
    const side = sideOf(gut);
    const all = hostRows(host);
    const sameSide = sel.side === side || !inSplit(start);
    const keep = (e.metaKey || e.ctrlKey) && sel.host === host && sameSide ? sel.rows.filter((r) => r !== start) : [];
    const scroller = gut.closest(".files-body");
    let last = start;
    let y = e.clientY;
    let raf = 0;
    const pick = () => {
      const el = document.elementFromPoint(gut.getBoundingClientRect().left + 4, y);
      const r = el && el.closest(".row, .half") && rowOf(el);
      if (r && all.includes(r)) last = r;
      if (last === start && !dragged) return;
      dragged = true;
      const a = all.indexOf(start);
      const b = all.indexOf(last);
      anchor = start;
      select(host, [...keep, ...all.slice(Math.min(a, b), Math.max(a, b) + 1)], { side });
    };
    // near an edge, keep scrolling so a long range can be reached
    const edge = () => {
      const box = scroller ? scroller.getBoundingClientRect() : { top: 0, bottom: innerHeight };
      const hr = host.getBoundingClientRect();
      let d = y < box.top + 48 ? -14 : y > box.bottom - 48 ? 14 : 0;
      if ((d > 0 && hr.bottom < box.bottom - 48) || (d < 0 && hr.top > box.top + 48)) d = 0;
      if (d) {
        quiet(400);
        scroller ? (scroller.scrollTop += d) : scrollBy(0, d);
        pick();
      }
      raf = requestAnimationFrame(edge);
    };
    const move = (ev) => {
      y = ev.clientY;
      pick();
    };
    const up = () => {
      cancelAnimationFrame(raf);
      removeEventListener("pointermove", move);
      removeEventListener("pointerup", up);
      removeEventListener("pointercancel", up);
      body.classList.remove("row-drag");
    };
    body.classList.add("row-drag");
    addEventListener("pointermove", move);
    addEventListener("pointerup", up);
    addEventListener("pointercancel", up);
    raf = requestAnimationFrame(edge);
  });

  document.addEventListener("click", (e) => {
    if (!pop.hidden && !e.target.closest('#trace-pop, [data-act="trace-menu"]')) setPop(false);
    // a click outside the definition panel closes it, and does nothing else unless it lands on a control
    if (!defEl.hidden && help.hidden && !e.target.closest("#def, [data-d]") && !String(getSelection()).length) {
      closeDef();
      if (!e.target.closest("a, button, summary, [data-act]")) return;
    }
    const t = e.target.closest("[data-act]");
    if (t) {
      const f = t.closest("figure.frame");
      switch (t.dataset.act) {
        case "reviewed":
          toggleReviewed(f);
          break;
        case "frame-toggle":
          setFrame(f, !f.classList.contains("collapsed"));
          break;
        case "view":
          setView(t.dataset.view);
          break;
        case "notes":
          toggleNotes();
          break;
        case "files":
          openFiles(f || frameNearCenter());
          break;
        case "close-files":
          closeFiles();
          break;
        case "fd-toggle": {
          const file = t.closest(".fd-file");
          setFdFile(file, !file.classList.contains("collapsed"));
          break;
        }
        case "fd-all": {
          const all = $$(".fd-file", files);
          const collapse = all.some((x) => !x.classList.contains("collapsed"));
          all.forEach((x) => setFdFile(x, collapse, false));
          syncFdAll();
          fdFill();
          break;
        }
        case "trace-menu":
          setPop(pop.hidden, { focus: e.detail === 0 });
          break;
        case "trace-next":
          stepTrace(1);
          break;
        case "trace-prev":
          stepTrace(-1);
          break;
        case "trace-clear":
          setPop(false);
          setTrace(null);
          break;
        case "side":
        case "map-mini":
          toggleSide();
          break;
        case "map-home":
          resetMap();
          break;
        case "help":
          setHelp(true);
          break;
        case "help-close":
          setHelp(false);
          break;
        case "branch": {
          const br = document.getElementById(t.getAttribute("aria-controls"));
          setBranch(br, !br.classList.contains("open"));
          break;
        }
        case "unfold": {
          const g = t.closest(".gap");
          unfold(g._u || g, t.dataset.x, e.shiftKey);
          break;
        }
        case "refold":
          // inside a <summary> the click would also toggle the file
          e.preventDefault();
          refold(t.closest(HOST));
          break;
        case "def-close":
          closeDef();
          break;
        case "def-prev":
        case "def-next": {
          const n = defNow.ids.length;
          showDef(defNow.ids, (defNow.k + (t.dataset.act === "def-next" ? 1 : n - 1)) % n);
          break;
        }
        case "branch-close": {
          const br = t.closest(".branch-wrap");
          const fork = forkOf(br);
          setBranch(br, false);
          if (fork && fork.getBoundingClientRect().top < 0) goTo(fork, { block: "center", glow: false });
          break;
        }
      }
      return;
    }
    if (!help.hidden && !e.target.closest(".sheet-in")) {
      setHelp(false);
      return;
    }
    const pick = e.target.closest("#trace-pop button[data-tr]");
    if (pick) {
      setPop(false);
      setTrace(pick.dataset.tr);
      stepTrace(1);
      return;
    }
    // a header folds its frame; its path and counts stay selectable text
    const fh = e.target.closest("figure.frame > .fh");
    if (fh && $(".fh-tog", fh) && !e.target.closest(".path, .stat, a, button")) {
      setFrame(fh.parentElement, !fh.parentElement.classList.contains("collapsed"));
      return;
    }
    const head = e.target.closest(".fd-head");
    if (head && !e.target.closest(".path, .stat, a, button")) {
      const file = head.closest(".fd-file");
      setFdFile(file, !file.classList.contains("collapsed"));
      return;
    }
    const back = e.target.closest(".fd-back");
    if (back) {
      closeFiles();
      const el = document.getElementById(back.dataset.goto);
      if (el) setTimeout(() => goTo(el, { block: "center" }), 20);
      return;
    }
    const nav = e.target.closest(".files-nav a");
    if (nav) {
      e.preventDefault();
      const el = document.getElementById(nav.dataset.fd);
      if (el) {
        setFdFile(el, false);
        fillIn(el).then(() => scrollFd(el));
      }
      return;
    }
    const why = e.target.closest(".attach .why");
    if (why) {
      showAttach(why.closest(".attach"));
      return;
    }
    if (e.target.closest(".ghjump")) return;
    const tr = e.target.closest(".tr");
    const named = e.target.closest("[data-d]");
    // a name that leads to its definition and also starts a trace: the click opens, alt-click traces
    if (named && !(e.altKey && tr && traceable(tr)) && !String(getSelection()).length) {
      // a hop inside the panel keeps it where it is
      showDef(named.dataset.d.split(" "), 0, named.closest("#def") ? null : { x: e.clientX, y: e.clientY });
      return;
    }
    if (tr && traceable(tr)) {
      setTrace(tr.dataset.tr === traceOn ? null : tr.dataset.tr, tr);
      return;
    }
    const line = e.target.closest(".code .row, .code .srow");
    if (line) {
      if (dragged) return (dragged = false);
      if (!e.shiftKey && String(getSelection()).length) return;
      const host = line.closest(HOST);
      const r = rowOf(e.target);
      const side = sideOf(e.target);
      const rows = host ? hostRows(host) : [];
      if (!r || !rows.includes(r)) return;
      // sides only matter while split shows; a restored selection keeps its side in unified too
      const sameSide = sel.side === side || !inSplit(r);
      const same = sel.host === host && sameSide;
      if ((e.metaKey || e.ctrlKey) && same) {
        anchor = r;
        select(host, sel.rows.includes(r) ? sel.rows.filter((x) => x !== r) : [...sel.rows, r], { side });
      } else if (e.shiftKey && anchor && same) {
        const a = rows.indexOf(anchor);
        const b = rows.indexOf(r);
        select(host, rows.slice(Math.min(a, b), Math.max(a, b) + 1), { side: sel.side });
      } else if (sel.rows.length === 1 && sel.rows[0] === r && sameSide) {
        anchor = null;
        select(host, []);
      } else {
        anchor = r;
        select(host, [r], { side });
      }
    }
  });

  document.addEventListener("keydown", (e) => {
    const why = e.target.closest && e.target.closest(".attach .why");
    if (why && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      showAttach(why.closest(".attach"));
    }
  });

  addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey || e.target.closest("input, textarea, select")) return;
    const k = e.key;
    if (k === "Escape") {
      if (!help.hidden) setHelp(false);
      else if (!defEl.hidden) closeDef();
      else if (!files.hidden) closeFiles();
      else if (!pop.hidden) setPop(false);
      else if (traceOn) setTrace(null);
      else if (sel.rows.length) select(sel.host, []);
      else if (narrow.matches && body.classList.contains("side-open-m")) toggleSide();
      else $$(".branch-wrap.open").forEach((b) => setBranch(b, false));
    } else if (k === "?") {
      setHelp(help.hidden);
    } else if (!help.hidden) {
      return;
    } else if (TOUR && "fsr".includes(k)) {
      return;
    } else if (k === "f") {
      files.hidden ? openFiles(frameNearCenter()) : closeFiles();
    } else if (!files.hidden) {
      return;
    } else if (k === "s") {
      setView(effView() === "split" ? "unified" : "split");
    } else if (k === "n") {
      toggleNotes();
    } else if (k === "m") {
      toggleSide();
    } else if (k === "j" || k === "k") {
      const i = Math.max(0, chapters.indexOf(active));
      const next = chapters[clamp(i + (k === "j" ? 1 : -1), 0, chapters.length - 1)];
      if (next) goTo(next, { glow: false });
    } else if (k === "t" || k === "T") {
      const i = synList.indexOf(body.dataset.syn || "");
      setSyn(synList[(i + (k === "T" ? -1 : 1) + synList.length) % synList.length], true);
    } else if (k === "]") {
      stepTrace(1);
    } else if (k === "[") {
      stepTrace(-1);
    } else if (k === "r") {
      const f = frameNearCenter();
      if (f) {
        toggleReviewed(f);
        toast(isReviewed(f) ? `Reviewed ${f.dataset.path}` : `Unmarked ${f.dataset.path}`);
      }
    } else {
      return;
    }
    e.preventDefault();
  });
  addEventListener("hashchange", readHash);

  // copied code gets back what git has: real-space indentation, and empty lines without the placeholder space
  document.addEventListener("copy", (e) => {
    const s = getSelection();
    const at = s.rangeCount && s.getRangeAt(0).commonAncestorContainer;
    const el = at && (at.nodeType === 1 ? at : at.parentElement);
    if (!el || !el.closest("main, #files, #def") || !(el.closest(".code") || el.querySelector(".code"))) return;
    const text = s.toString().replace(/^\u00a0+/gm, (m) => " ".repeat(m.length)).replace(/^ $/gm, "");
    e.clipboardData.setData("text/plain", text);
    e.preventDefault();
  });

  // ---------- header fit: the two pieces never overlap ----------

  const hdrL = $(".hdr-l");
  const hdrR = $(".hdr-r");
  function fitHdr() {
    body.classList.remove("hdr-tight", "hdr-norefs");
    if (narrow.matches) return;
    const left = hdrL.offsetLeft;
    const room = () => innerWidth - 16 - hdrR.offsetWidth - 12 - left;
    // drop the labels first, so the title keeps a readable width
    if (room() < 240) body.classList.add("hdr-tight");
    else if (room() - $(".refs", hdrL).offsetWidth < $(".t-title", hdrL).scrollWidth + 44) body.classList.add("hdr-norefs");
    root.style.setProperty("--hdr-l-max", `${Math.max(48, room())}px`);
  }
  addEventListener("resize", fitHdr);
  if ("ResizeObserver" in window) new ResizeObserver(fitHdr).observe(hdrR);

  // ---------- init ----------

  pill.inert = true;
  for (const u of $$(".code.u[data-src]")) {
    if (u.querySelector(":scope > [data-len]")) u._lazy = true;
    else setup(u);
  }
  applySide();
  fitHdr();
  applyView();
  applyNotes();
  refreshReviewed();
  for (const f of diffFrames) if (isReviewed(f)) setFrame(f, true, false);
  syncFdAll();
  spy();
  updateMap();
  // labels rewrap and branches come and go: the fill is a share of the list's height
  if ("ResizeObserver" in window && $("ol", map)) new ResizeObserver(placeFill).observe($("ol", map));
  readHash();
  if (document.fonts) document.fonts.ready.then(queueWires);
  addEventListener("load", queueWires);
})();
