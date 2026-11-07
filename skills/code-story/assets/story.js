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
      return;
    }
    const d = y - lastY;
    if (Math.abs(d) < 6) return;
    if (d > 0 && y > 160 && pop.hidden) setHdr(true);
    else if (d < 0) setHdr(false);
    lastY = y;
  }
  addEventListener("mousemove", (e) => {
    if (hdrHidden && e.clientY < 56) setHdr(false);
  });
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
  const cancelAnchor = () => anchorRun++;
  addEventListener("wheel", cancelAnchor, { passive: true });
  addEventListener("touchmove", cancelAnchor, { passive: true });
  addEventListener("pointerdown", cancelAnchor, true);
  function keepAnchor(fn, ms = 480) {
    const run = ++anchorRun;
    const at = anchorFor();
    const t0 = at ? at().getBoundingClientRect().top : 0;
    fn();
    if (!at) return;
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
    };
    tick();
  }

  // open whatever hides `el`: a closed branch or <details>
  function reveal(el) {
    const brs = [];
    for (let b = el.closest(".branch-wrap"); b; b = b.parentElement.closest(".branch-wrap")) brs.unshift(b);
    for (const br of brs) if (!br.classList.contains("open")) setBranch(br, true, { instant: true });
    for (let d = el.closest("details"); d; d = d.parentElement && d.parentElement.closest("details")) d.open = true;
  }
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
    h.className = `half ${kindOf(row)}`;
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
      if (!k.classList.contains("row") || kindOf(k) === "c") {
        s.append(k.classList.contains("row") ? srow(k, k) : k.cloneNode(true));
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
  const SPLITTABLE = "figure.frame.diff > .code.u, .rip-site > .code.u, details.file-item > .code.u, .fd-hunk > .code.u";

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
  function applyView() {
    const on = effView() === "split";
    for (const u of $$(SPLITTABLE)) {
      const here = on && (fdRoomy || !u.closest("#files"));
      if (!here && !hasSplit(u)) continue;
      const s = hasSplit(u) ? u.nextElementSibling : buildSplit(u);
      u.hidden = here;
      s.hidden = !here;
    }
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
  function spy() {
    const y = innerHeight * 0.36;
    let cur = chapters[0];
    for (const ch of chapters) if (ch.getBoundingClientRect().top <= y) cur = ch;
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
      $(".side-f .bar i").style.width = `${(100 * k) / (numbered.length || 1)}%`;
      $(".side-f .f-txt").textContent = `Chapter ${k} of ${numbered.length}`;
    }
    const li = nodes.get(active);
    const fill = $(".fill", map);
    if (li && fill) fill.style.height = `${Math.max(0, li.offsetTop + 4)}px`;
    if (li && !side.matches(":hover")) {
      const sc = $(".side-scroll", side);
      const r = li.getBoundingClientRect();
      const b = sc.getBoundingClientRect();
      if (b.height && (r.top < b.top || r.bottom > b.bottom)) sc.scrollTop += r.top - b.top - b.height / 3;
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
        b.title = on ? "Reviewed (r to undo)" : "Mark reviewed (r)";
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
    $(".side-f .bar i").style.width = `${(100 * done) / (n || 1)}%`;
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
    $(".tp-count").textContent = `${lit.length} ${lit.length === 1 ? "frame" : "frames"}`;
    traceIdx = origin ? lit.indexOf(holder(origin)) : -1;
    if (traceIdx >= 0) lit[traceIdx].classList.add("current");
  }
  function stepTrace(d) {
    if (!traceOn || !lit.length) return;
    if (traceIdx >= 0) lit[traceIdx].classList.remove("current");
    traceIdx = (traceIdx + d + lit.length) % lit.length;
    const f = lit[traceIdx];
    f.classList.add("current");
    reveal(f);
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
  function openFiles(frame, target) {
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
      scrollFd(target, 60);
      flash(target);
    }
    fdSpy();
  }
  function closeFiles() {
    if (files.hidden) return;
    files.hidden = true;
    body.classList.remove("files-open");
    closeModal(files);
  }
  function setFdFile(file, collapsed) {
    file.classList.toggle("collapsed", collapsed);
    const b = $(".fd-tog", file);
    b.setAttribute("aria-expanded", String(!collapsed));
    b.setAttribute("aria-label", collapsed ? "Expand file" : "Collapse file");
    syncFdAll();
  }
  function syncFdAll() {
    const anyOpen = $$(".fd-file", files).some((f) => !f.classList.contains("collapsed"));
    $('[data-act="fd-all"]', files).textContent = anyOpen ? "Collapse all" : "Expand all";
  }
  function fdSpy() {
    const top = fdBody.getBoundingClientRect().top + 40;
    let cur = null;
    for (const f of $$(".fd-file", files)) if (f.getBoundingClientRect().top <= top) cur = f;
    cur = cur || $(".fd-file", files);
    $$(".files-nav a", files).forEach((a) => {
      const on = !!cur && a.dataset.fd === cur.id;
      a.classList.toggle("cur", on);
      if (on) a.setAttribute("aria-current", "true");
      else a.removeAttribute("aria-current");
    });
  }
  fdBody.addEventListener("scroll", () => requestAnimationFrame(fdSpy), { passive: true });
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
  document.addEventListener("mouseover", (e) => {
    const line = e.target.closest(".row, .half");
    if (line && !narrow.matches) putGh(line);
    onHoverLinks(e);
  });

  // a selection belongs to a host: a story frame, an appendix file or a full-diff hunk
  const HOST = "figure.frame, details.file-item, .fd-hunk";
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
    const idx = rows.filter((r) => onSide(r, side)).map((r) => all.indexOf(r)).sort((a, b) => a - b);
    const out = [];
    for (const i of idx) {
      const last = out[out.length - 1];
      if (last && i === last[1] + 1) last[1] = i;
      else out.push([i, i]);
    }
    return out.map(([a, b]) => lineKey(all[a], side) + (b > a ? `-${lineKey(all[b], side)}` : "")).join(",");
  }
  function select(host, rows, { scroll = false, hash = true, side = null } = {}) {
    if (host) rows = hostRows(host).filter((r) => rows.includes(r) && (!inSplit(r) || onSide(r, side)));
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
  function readHash() {
    const m = /^#(.+?)-([LR]\d+(?:-[LR]\d+)?(?:,[LR]\d+(?:-[LR]\d+)?)*)$/.exec(decodeURIComponent(location.hash));
    if (!m) return;
    const host = document.getElementById(m[1]);
    if (!host || !host.matches(HOST)) return;
    if (files.contains(host)) openFiles(null, host);
    const rows = hostRows(host);
    const find = (k) => rows.findIndex((r) => (k[0] === "L" ? r.dataset.o : r.dataset.n) === k.slice(1));
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
  function onHoverLinks(e) {
    const next = new Set();
    const att = e.target.closest(".attach");
    if (att) next.add(att);
    const line = !att && e.target.closest(".row, .half");
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
        if (att.hidden || !frame) continue;
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
  document.addEventListener("toggle", queueWires, true);
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
    const t = e.target.closest("[data-act]");
    if (t) {
      const f = t.closest("figure.frame");
      switch (t.dataset.act) {
        case "reviewed":
          toggleReviewed(f);
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
          all.forEach((x) => setFdFile(x, collapse));
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
        scrollFd(el);
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
    if (!el || !el.closest("main, #files") || !(el.closest(".code") || el.querySelector(".code"))) return;
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
  applySide();
  fitHdr();
  applyView();
  applyNotes();
  refreshReviewed();
  syncFdAll();
  spy();
  updateMap();
  readHash();
  if (document.fonts) document.fonts.ready.then(queueWires);
  addEventListener("load", queueWires);
})();
