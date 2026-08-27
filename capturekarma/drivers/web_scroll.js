// Installed via add_init_script. Animates scroll deterministically with requestAnimationFrame.
(() => {
  const EASE = {
    linear: t => t,
    ease_in_out_cubic: t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
    ease_out_cubic: t => 1 - Math.pow(1 - t, 3),
    ease_in_out_quint: t => (t < 0.5 ? 16 * Math.pow(t, 5) : 1 - Math.pow(-2 * t + 2, 5) / 2),
  };
  window.__ckSmoothScroll = function (containerSelector, by, to, durationMs, easingName) {
    const ease = EASE[easingName] || EASE.ease_in_out_cubic;
    const el = containerSelector ? document.querySelector(containerSelector) : null;
    if (containerSelector && !el) return Promise.reject(new Error("scroll container not found: " + containerSelector));
    const target = el || document.scrollingElement || document.documentElement;
    const start = target.scrollTop;
    const max = target.scrollHeight - target.clientHeight;
    const goal = Math.max(0, Math.min(max, to !== null && to !== undefined ? to : start + by));
    if (goal === start || durationMs <= 0) { target.scrollTop = goal; return Promise.resolve(target.scrollTop); }
    return new Promise(resolve => {
      let t0 = null;
      const step = now => {
        if (t0 === null) t0 = now;
        const p = Math.min(1, (now - t0) / durationMs);
        target.scrollTop = start + (goal - start) * ease(p);
        if (p < 1) requestAnimationFrame(step);
        else { target.scrollTop = goal; resolve(target.scrollTop); }
      };
      requestAnimationFrame(step);
    });
  };
})();
