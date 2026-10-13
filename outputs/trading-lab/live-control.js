/* Live ARM / DISARM control — phone-friendly */
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }

  function ensurePanel() {
    if ($("liveArmPanel")) return;
    var host = $("command-deck") || $("memeTraderStatus") || document.body;
    var panel = document.createElement("section");
    panel.id = "liveArmPanel";
    panel.className = "sec";
    panel.style.cssText = "margin:12px 0;padding:14px;border:1px solid #1a3a2a;border-radius:12px;background:#0a1210;";
    panel.innerHTML =
      '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">' +
      '<div><strong style="color:#e8fff6">LIVE RISK GATE</strong>' +
      '<div id="liveArmMeta" style="font-size:12px;color:#7a9a8a;margin-top:4px">Loading…</div></div>' +
      '<div style="display:flex;gap:8px">' +
      '<button id="liveArmBtn" class="btn go" style="min-width:96px">ARM</button>' +
      '<button id="liveDisarmBtn" class="btn" style="min-width:96px">DISARM</button>' +
      "</div></div>" +
      '<div id="liveArmLimits" style="margin-top:10px;font-size:12px;color:#9ab;font-family:monospace"></div>' +
      '<div id="liveArmMsg" style="margin-top:8px;font-size:12px;color:#8a9"></div>';
    if (host.firstChild) host.insertBefore(panel, host.firstChild);
    else host.appendChild(panel);

    $("liveArmBtn").addEventListener("click", function () { act("arm"); });
    $("liveDisarmBtn").addEventListener("click", function () { act("disarm"); });
  }

  async function api(path, body) {
    var opts = body
      ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
      : {};
    var r = await fetch(path, opts);
    var j = await r.json().catch(function () { return {}; });
    if (!r.ok) throw new Error(j.error || r.statusText || "request failed");
    return j;
  }

  function paint(s) {
    ensurePanel();
    var armed = !!(s && s.armed);
    var meta = $("liveArmMeta");
    var limits = $("liveArmLimits");
    if (meta) {
      meta.textContent = armed
        ? ("ARMED · " + (s.seconds_remaining || 0) + "s left · daily loss $" +
           Number(s.daily_realized_loss_usd || 0).toFixed(2) + " / $" +
           Number(s.max_daily_loss_usd || 0).toFixed(0))
        : ("DISARMED · new live orders frozen · daily loss $" +
           Number(s.daily_realized_loss_usd || 0).toFixed(2));
      meta.style.color = armed ? "#00f5a0" : "#f5a0a0";
    }
    if (limits) {
      limits.textContent =
        "wallet $" + Number(s.wallet_cap_usd || 100).toFixed(0) +
        " · max/trade $" + Number(s.max_per_trade_usd || 0).toFixed(0) +
        " · max loss/day $" + Number(s.max_daily_loss_usd || 0).toFixed(0) +
        " · max positions " + (s.max_open_positions || 0) +
        " · max exposure $" + Number(s.max_exposure_usd || 0).toFixed(0);
    }
    var armBtn = $("liveArmBtn");
    var disarmBtn = $("liveDisarmBtn");
    if (armBtn) armBtn.disabled = armed;
    if (disarmBtn) disarmBtn.disabled = !armed;
  }

  async function refresh() {
    try {
      var s = await api("/api/live/status");
      paint(s);
      var msg = $("liveArmMsg");
      if (msg && s.note) msg.textContent = s.note;
    } catch (e) {
      ensurePanel();
      var meta = $("liveArmMeta");
      if (meta) meta.textContent = "Live gate unavailable: " + e.message;
    }
  }

  async function act(kind) {
    var msg = $("liveArmMsg");
    try {
      if (msg) msg.textContent = kind === "arm" ? "Arming…" : "Disarming…";
      var s = await api(kind === "arm" ? "/api/live/arm" : "/api/live/disarm", {
        actor: "phone_operator",
      });
      paint(s);
      if (msg) {
        msg.textContent = kind === "arm"
          ? "ARMED for up to 24h. Agents still cannot bypass limits."
          : "DISARMED. All new live orders frozen.";
      }
    } catch (e) {
      if (msg) msg.textContent = e.message;
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      ensurePanel();
      refresh();
      setInterval(refresh, 15000);
    });
  } else {
    ensurePanel();
    refresh();
    setInterval(refresh, 15000);
  }
})();
