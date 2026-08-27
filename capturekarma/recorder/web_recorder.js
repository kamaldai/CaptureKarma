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
    const text = (el.innerText || "").trim();
    if (text && text.length <= 40 && ["button", "a", "label", "summary"].includes(tag)) {
      const s = `${tag}:has-text("${text.replace(/"/g, '\\"')}")`;
      const matches = Array.from(document.querySelectorAll(tag)).filter(n => (n.innerText || "").trim() === text);
      if (matches.length === 1) return s;
    }
    const path = cssPath(el);
    return unique(path) ? path : null;
  }

  // The binding is gone once the recorder detaches (page closing, navigation racing stop()):
  // losing an event then is expected, and throwing here would break the page under the user.
  const send = payload => { try { window.__ck_event(JSON.stringify(payload)); } catch (e) {} };

  document.addEventListener("click", e => {
    const button = ["left", "middle", "right"][e.button] || "left";
    send({ kind: "click", selector: uniqueSelector(e.target), at: [Math.round(e.clientX), Math.round(e.clientY)], button });
  }, true);

  const lastTop = new WeakMap();
  const pending = new Map();
  function scrollTargetOf(e) {
    return (e.target === document || e.target === document.documentElement || e.target === document.body)
      ? null : e.target;
  }
  document.addEventListener("scroll", e => {
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
