/* Prefer FastAPI books when available; fall back silently */
(function () {
  "use strict";
  var API_BASE = localStorage.getItem("tradinglab_api_base") || "";

  async function tryFetch(path, opts) {
    var url = (API_BASE || "") + path;
    var r = await fetch(url, opts || { headers: { Accept: "application/json" } });
    if (!r.ok) throw new Error(String(r.status));
    return r.json();
  }

  async function booksSummary() {
    try {
      return await tryFetch("/api/books/summary");
    } catch (e) {
      return null;
    }
  }

  async function enrich() {
    var summary = await booksSummary();
    if (!summary) return;
    var risk = summary.risk || {};
    var el = document.getElementById("uMode");
    if (el && risk.armed != null) {
      var mode = (localStorage.getItem("tradinglab_mode") || "meme").toUpperCase();
      el.textContent = mode + (risk.armed ? " · ARM" : " · SAFE");
    }
    var armChip = document.getElementById("liveArmState");
    if (armChip) armChip.textContent = risk.armed ? "ARMED" : "DISARMED";
    window.__booksSummary = summary;
  }

  function boot() {
    enrich();
    setInterval(enrich, 30000);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  window.TradingLabBridge = { booksSummary: booksSummary, enrich: enrich };
})();
