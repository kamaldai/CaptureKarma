// Init script: report user actions to Python via the exposed binding window.__ck_event(json).
(() => {
  if (window.__ckRecorderInstalled) return;
  window.__ckRecorderInstalled = true;

  const cssEscape = s => (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/([^\w-])/g, "\\$1");
  const unique = sel => { try { return document.querySelectorAll(sel).length === 1; } catch (e) { return false; } };

  function cssPath(el) {
    const parts = [];
    while (el && el.nodeType === 1 && el !== document.body) {
      let part = el.tagName.toLowerCase();
      const parent = el.parentElement;
      if (parent) {
        const same = Array.from(parent.children).filter(c => c.tagName === el.tagName);
        if (same.length > 1) part += `:nth-of-type(${same.indexOf(el) + 1})`;
      }
      parts.unshift(part);
      el = parent;
    }
    return "body > " + parts.join(" > ");
  }

  function uniqueSelector(el) {
    // Clicks land on inner spans/icons; walk up to the nearest interactive element first.
    const interactive = el.closest("button, a, input, select, textarea, [role=button], [role=link], [data-testid], label");
    if (interactive) el = interactive;
    const tid = el.getAttribute("data-testid");
    if (tid) { const s = `[data-testid="${tid}"]`; if (unique(s)) return s; }
    if (el.id) { const s = "#" + cssEscape(el.id); if (unique(s)) return s; }
    const tag = el.tagName.toLowerCase();
    const label = el.getAttribute("aria-label");
    if (label) { const s = `${tag}[aria-label="${label}"]`; if (unique(s)) return s; }
    if (el.classList.length) {
      const s = tag + "." + Array.from(el.classList).map(cssEscape).join(".");
      if (unique(s)) return s;
    }
    // Playwright's :has-text() is a case-insensitive *substring* match over the element's
    // whitespace-normalised textContent -- not innerText, whose line breaks (a badge stacked over
    // a label) both fail to match and cannot even be quoted inside a CSS selector: a raw newline
    // there is a parse error. So normalise textContent, and check uniqueness the way Playwright
    // will actually match, or "Save" would be recorded as unique next to a "Save all" button.
    const norm = s => (s || "").replace(/\s+/g, " ").trim();
    const text = norm(el.textContent);
    if (text.length >= 1 && text.length <= 40 && ["button", "a", "label", "summary"].includes(tag)) {
      const needle = text.toLowerCase();
      const matches = Array.from(document.querySelectorAll(tag))
        .filter(n => norm(n.textContent).toLowerCase().includes(needle));
      if (matches.length === 1) return `${tag}:has-text("${text.replace(/"/g, '\\"')}")`;
    }
    const path = cssPath(el);
    return unique(path) ? path : null;
  }

  // The binding is gone once the recorder detaches (page closing, navigation racing stop()):
  // losing an event then is expected, and throwing here would break the page under the user.
  const send = payload => { try { window.__ck_event(JSON.stringify(payload)); } catch (e) {} };

  // ---- clicks and drags -------------------------------------------------------------------
  // A press that travels (orbiting a 3D viewer, moving a slider) is a drag, not a click. Both
  // arrive as pointerdown/up, and the browser fires a synthetic `click` after the up either way,
  // so a recognised drag sets suppressClick to keep that click out of the scene.
  // Thresholds are mirrored in recorder/desktop.py; keep the two in step.
  const DRAG_SAMPLE_MS = 40, DRAG_SAMPLE_PX = 8, DRAG_MIN_PX = 6, DRAG_MIN_MS = 300;
  let drag = null;
  let suppressClick = false;

  const BUTTONS = ["left", "middle", "right"];
  const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);

  document.addEventListener("pointerdown", e => {
    drag = null;
    if (e.button < 0 || e.button > 2) return;
    const p = [Math.round(e.clientX), Math.round(e.clientY)];
    drag = { path: [p], button: BUTTONS[e.button], t0: e.timeStamp, lastT: e.timeStamp, id: e.pointerId };
  }, true);

  document.addEventListener("pointermove", e => {
    if (!drag || e.pointerId !== drag.id) return;
    const p = [Math.round(e.clientX), Math.round(e.clientY)];
    if (e.timeStamp - drag.lastT >= DRAG_SAMPLE_MS || dist(p, drag.path[drag.path.length - 1]) >= DRAG_SAMPLE_PX) {
      drag.path.push(p);
      drag.lastT = e.timeStamp;
    }
  }, true);

  document.addEventListener("pointerup", e => {
    const d = drag;
    drag = null;
    if (!d || e.pointerId !== d.id) return;
    const p = [Math.round(e.clientX), Math.round(e.clientY)];
    const last = d.path[d.path.length - 1];
    if (p[0] !== last[0] || p[1] !== last[1]) d.path.push(p);
    let length = 0;
    for (let i = 1; i < d.path.length; i++) length += dist(d.path[i - 1], d.path[i]);
    const duration = e.timeStamp - d.t0;
    const moved = d.path.length > 1;
    if (moved && (length >= DRAG_MIN_PX || duration >= DRAG_MIN_MS)) {
      suppressClick = true;   // cleared by the click handler below, whichever way it goes
      send({ kind: "drag", path: d.path, button: d.button, duration_ms: Math.round(duration) });
    }
  }, true);

  // Losing the pointer mid-gesture (a drag off the window, a context menu, alt-tab) means we never
  // see the release: throw the half-recorded path away rather than guess where it ended.
  document.addEventListener("pointercancel", () => { drag = null; }, true);
  window.addEventListener("blur", () => { drag = null; }, true);

  document.addEventListener("click", e => {
    const wasDrag = suppressClick;
    suppressClick = false;
    if (wasDrag) return;
    const button = BUTTONS[e.button] || "left";
    send({ kind: "click", selector: uniqueSelector(e.target), at: [Math.round(e.clientX), Math.round(e.clientY)], button });
  }, true);

  // ---- canvas wheel -----------------------------------------------------------------------
  // A wheel over a canvas that zooms (and calls preventDefault) produces no `scroll` event at
  // all, so the scroll listener below never sees it. Accumulate a burst; if a scroll did fire
  // while it was open the page really did move and the scroll path already reported it.
  const WHEEL_BURST_MS = 150;
  const LINE_PX = 16;
  let wheelBurst = null;

  function flushWheel() {
    const b = wheelBurst;
    wheelBurst = null;
    if (!b) return;
    if (b.scrolled) return;                       // the page moved: `scroll` already recorded it
    if (Math.abs(b.total) < 1) return;
    send({ kind: "wheel", delta: Math.round(b.total), at: b.at });
  }

  document.addEventListener("wheel", e => {
    let dy = e.deltaY;
    if (e.deltaMode === 1) dy *= LINE_PX;                       // DOM_DELTA_LINE
    else if (e.deltaMode === 2) dy *= window.innerHeight;       // DOM_DELTA_PAGE
    if (!wheelBurst) wheelBurst = { total: 0, at: [Math.round(e.clientX), Math.round(e.clientY)], scrolled: false };
    wheelBurst.total += dy;
    clearTimeout(wheelBurst.timer);
    wheelBurst.timer = setTimeout(flushWheel, WHEEL_BURST_MS);
  }, { capture: true, passive: true });

  const lastTop = new WeakMap();
  const pending = new Map();
  function scrollTargetOf(e) {
    return (e.target === document || e.target === document.documentElement || e.target === document.body)
      ? null : e.target;
  }
  document.addEventListener("scroll", e => {
    if (wheelBurst) wheelBurst.scrolled = true;
    const el = scrollTargetOf(e);
    const scroller = el || document.scrollingElement || document.documentElement;
    const top = scroller.scrollTop;
    const prev = lastTop.has(scroller) ? lastTop.get(scroller) : 0;
    lastTop.set(scroller, top);
    const delta = Math.round(top - prev);
    if (!delta) return;
    const key = el || document;
    const acc = (pending.get(key) || 0) + delta;
    pending.set(key, acc);
    if (!key.__ckScrollTimer) {
      key.__ckScrollTimer = setTimeout(() => {
        key.__ckScrollTimer = null;
        const total = pending.get(key) || 0;
        pending.delete(key);
        if (total) send({ kind: "scroll", container: el ? uniqueSelector(el) : null, delta: total });
      }, 100);
    }
  }, true);

  const STOP_KEYS = new Set(["F9", "Escape"]);
  const isPasswordField = el =>
    !!el && el.nodeType === 1 && el.tagName === "INPUT" && String(el.type).toLowerCase() === "password";

  document.addEventListener("keydown", e => {
    if (e.isComposing) return;
    if (STOP_KEYS.has(e.key)) return;          // the stop hotkeys are never part of the demo
    if (isPasswordField(e.target)) return;     // privacy: passwords never reach the scene file
    send({ kind: "key", key: e.key });
  }, true);
})();
