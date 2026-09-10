/* Injected by main.py run_manual() / run_auto(): a fixed column of buttons in
   the TOP-RIGHT that call the Python handlers registered with
   page.expose_function(). Loaded via page.add_init_script() so it re-runs on
   every navigation, and also evaluated once against the current document.
   ensure() is idempotent: once the bar + buttons exist it writes NOTHING, so
   the MutationObserver / interval that re-add them after a SPA re-render can't
   feed back into themselves.

   Top frame only: iframe-hosted forms (iCIMS / Ashby / Greenhouse) would each
   render their own copy otherwise. The handlers are bound in every frame by
   Playwright, and the Python side scans all frames, so filling still works. */
(() => {
  if (window.top !== window) return;   // top frame only — no per-iframe duplicates

  // Bot-challenge / OAuth pages: don't inject anything. The MutationObserver +
  // interval below churn document.documentElement, which breaks Cloudflare's
  // Turnstile widget mid-run and loops the "security verification" forever
  // (instahyre Google SSO). Also keeps the bar off the Google consent screen.
  const _h = location.hostname, _p = location.pathname;
  if (
    _h === "challenges.cloudflare.com" ||
    _p.startsWith("/cdn-cgi/challenge-platform/") ||
    /^(accounts|login)\.google\.com$/.test(_h) ||
    _h === "accounts.youtube.com" ||
    document.title === "Just a moment..."
  ) return;

  const GREEN = "#1a7f37";
  const BAR_ID = "__agent_bar";
  const BTNS = [
    { id: "__agent_jd_btn",        label: "📋 Capture job description", fn: "__agentCaptureJD" },
    { id: "__agent_fill_btn",      label: "🤖 Fill this page",          fn: "__agentFill" },
    { id: "__agent_overwrite_btn", label: "🤖 Fill (overwrite)",        fn: "__agentFillOverwrite" },
    { id: "__agent_abort_btn",     label: "⏹ Abort fill",               fn: "__agentAbortFill" },
    { id: "__agent_fail_btn",      label: "❌ Mark application failed",  fn: "__agentMarkFailed" },
  ];

  function bar() {
    let el = document.getElementById(BAR_ID);
    if (el) return el;
    const parent = document.body || document.documentElement;
    if (!parent) return null;                             // DOM not ready — retried below
    el = document.createElement("div");
    el.id = BAR_ID;
    Object.assign(el.style, {
      position: "fixed", top: "12px", right: "12px", zIndex: "2147483647",
      display: "flex", flexDirection: "column", gap: "6px", alignItems: "flex-end",
      pointerEvents: "none",   // only the buttons themselves take clicks (see below)
    });
    parent.appendChild(el);
    return el;
  }

  function make(spec, host) {
    if (typeof window[spec.fn] !== "function") return;   // Python handler not bound
    if (document.getElementById(spec.id)) return;        // already on the page
    const b = document.createElement("button");
    b.id = spec.id;
    b.type = "button";
    b.textContent = spec.label;
    Object.assign(b.style, {
      pointerEvents: "auto",
      padding: "8px 12px", font: "600 13px/1.2 system-ui, -apple-system, sans-serif",
      color: "#fff", background: GREEN, border: "none", borderRadius: "8px",
      boxShadow: "0 2px 8px rgba(0,0,0,.35)", cursor: "pointer", whiteSpace: "nowrap",
    });
    b.addEventListener("click", async () => {
      if (b.disabled) return;
      const now = Date.now();
      if (now - (b.__lastRun || 0) < 1500) return;   // swallow rapid double-clicks
      b.__lastRun = now;
      b.disabled = true;
      b.style.opacity = "0.6";
      const label = b.__label || (b.__label = b.textContent);
      b.textContent = "… working";
      let ok = true, ret;
      try { ret = await window[spec.fn](); }
      catch (e) { ok = false; console.error("[agent]", e); }
      if (spec.id === "__agent_jd_btn" && ok) {
        // leave a visible "done" state so the user knows the JD was collected;
        // restore after a few seconds so a new page can be re-captured
        b.textContent = "✓ JD captured";
        b.style.background = "#57606a";
        setTimeout(() => {
          b.textContent = label;
          b.style.background = GREEN;
          b.style.opacity = "1";
          b.disabled = false;
        }, 4000);
      } else if (spec.id === "__agent_fail_btn" && ok) {
        // latched toggle: `ret` is true once this run is marked failed. Stay
        // visible in the armed state so the user can click again to undo.
        if (ret) {
          b.textContent = "☑ Will log as FAILED — click to undo";
          b.style.background = "#cf222e";
        } else {
          b.textContent = label;
          b.style.background = GREEN;
        }
        b.style.opacity = "1";
        b.disabled = false;
      } else {
        b.textContent = label;
        b.style.opacity = "1";
        b.disabled = false;
      }
    });
    host.appendChild(b);
  }

  function ensure() {
    const host = bar();
    if (!host) return;                                   // DOM not ready — retried below
    BTNS.forEach((spec) => make(spec, host));
    if (!window.__agentObserving && document.documentElement) {
      window.__agentObserving = true;
      try {
        new MutationObserver(ensure).observe(document.documentElement,
          { childList: true, subtree: true });
      } catch (e) { window.__agentObserving = false; }
    }
  }

  ensure();
  setTimeout(ensure, 0);
  setTimeout(ensure, 500);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ensure);
  }
  if (!window.__agentButtonsInterval) {
    window.__agentButtonsInterval = setInterval(ensure, 1500);
  }
})();
