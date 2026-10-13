/* Live ARM / DISARM + emergency data load if main script died */
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }

  function money(n) {
    var x = Number(n);
    if (!Number.isFinite(x)) return "—";
    var sign = x < 0 ? "-" : "";
    return sign + "$" + Math.abs(x).toFixed(2);
  }

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

  async function refreshArm() {
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

  async function emergencyLoad() {
    try {
      var s = await api("/api/meme/trader");
      var bal = $("deckBal");
      if (bal) bal.textContent = money(s.equity_usd);
      var sub = $("deckBalSub");
      if (sub) {
        sub.textContent =
          "cash " + money(s.cash_usd) + " · " + (s.open_positions_count || 0) + " open";
      }
      var pnl = $("deckPnl");
      if (pnl) {
        var start = Number(s.initial_cash_usd || 1000);
        var eq = Number(s.equity_usd);
        var d = eq - start;
        pnl.textContent = (d >= 0 ? "+" : "") + money(d);
        pnl.className = "pnl-val " + (d >= 0 ? "up" : "dn");
      }
      var st = $("memeTraderStatus");
      if (st) {
        var text = st.textContent || "";
        if (!text.trim() || /unavailable|Loading|—/.test(text) || st.children.length === 0) {
          var pos = Array.isArray(s.positions) ? s.positions : [];
          var open = pos.filter(function (p) {
            return String(p.status || "").toUpperCase() === "OPEN";
          });
          var rows = open
            .map(function (p) {
              return (
                "<tr><td>" +
                (p.symbol || p.token_address || "?") +
                "</td><td class=\"r mono\">" +
                money(p.entry_price) +
                "</td><td class=\"r mono\">" +
                money(p.current_price) +
                "</td><td class=\"r mono\">" +
                money(p.unrealized_pnl) +
                "</td></tr>"
              );
            })
            .join("");
          st.innerHTML =
            '<div class="notes">Equity ' +
            money(s.equity_usd) +
            " · realized " +
            money(s.realized_pnl_usd) +
            " · open " +
            (s.open_positions_count || 0) +
            "</div>" +
            (rows
              ? '<table class="tbl"><thead><tr><th>Sym</th><th class="r">Entry</th><th class="r">Px</th><th class="r">uPnL</th></tr></thead><tbody>' +
                rows +
                "</tbody></table>"
              : "<div class=\"notes\">No open positions.</div>");
        }
      }
      var live = $("deckLive");
      if (live) live.textContent = "LIVE";
      var status = $("deckStatus");
      if (status && /STANDBY|—|Loading/.test(status.textContent || "")) {
        status.textContent = "DATA LOADED";
      }
    } catch (e) {
      var st = $("memeTraderStatus");
      if (st && !(st.textContent || "").trim()) {
        st.innerHTML =
          '<div class="notes">Paper trader load failed: ' +
          String(e.message || e) +
          "</div>";
      }
    }
    try {
      var fx = await api("/api/forex");
      var eq = $("equity");
      if (eq && fx.account) {
        eq.textContent = money(fx.account.equity || fx.account.cash);
      }
    } catch (_) {}
  }

  function boot() {
    ensurePanel();
    refreshArm();
    emergencyLoad();
    setInterval(refreshArm, 15000);
    setInterval(emergencyLoad, 20000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
