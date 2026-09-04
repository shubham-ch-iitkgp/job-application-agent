/* Injected by main.py run_manual(): two fixed-position buttons that call the
   Python handlers registered with page.expose_function(). Loaded via
   page.add_init_script() so it re-runs on every navigation, and also evaluated
   once against the current document. ensure() is idempotent and re-runnable;
   a MutationObserver + interval re-add the buttons when a SPA (Workday)
   re-renders and wipes them. */
(() => {
  const BTNS = [
    { id: "__agent_jd_btn",   label: "📋 Capture job description", fn: "__agentCaptureJD", bottom: "56px" },
    { id: "__agent_fill_btn", label: "🤖 Fill this page",          fn: "__agentFill",      bottom: "12px" },
  ];

  function make(spec) {
    if (typeof window[spec.fn] !== "function") return;   // Python handler not bound
    if (document.getElementById(spec.id)) return;        // already on the page
    const parent = document.body || document.documentElement;
    if (!parent) return;                                 // DOM not ready — retried below
    const b = document.createElement("button");
    b.id = spec.id;
    b.type = "button";
    b.textContent = spec.label;
    Object.assign(b.style, {
      position: "fixed", right: "12px", bottom: spec.bottom, zIndex: "2147483647",
      padding: "8px 12px", font: "600 13px/1.2 system-ui, -apple-system, sans-serif",
      color: "#fff", background: "#1a7f37", border: "none", borderRadius: "8px",
      boxShadow: "0 2px 8px rgba(0,0,0,.35)", cursor: "pointer",
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
      let ok = true;
      try { await window[spec.fn](); }
      catch (e) { ok = false; console.error("[agent]", e); }
      if (spec.id === "__agent_jd_btn" && ok) {
        // leave a visible "done" state so the user on the page knows the JD
        // was collected; restore after a few seconds so a new page can be re-captured
        b.textContent = "✓ JD captured";
        b.style.background = "#57606a";
        setTimeout(() => {
          b.textContent = label;
          b.style.background = "#1a7f37";
          b.style.opacity = "1";
          b.disabled = false;
        }, 4000);
      } else {
        b.textContent = label;
        b.style.opacity = "1";
        b.disabled = false;
      }
    });
    parent.appendChild(b);
  }

  function ensure() {
    BTNS.forEach(make);
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
