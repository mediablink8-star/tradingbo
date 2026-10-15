/* Unified desk — one equity, one positions, one mode */
(function () {
  "use strict";
  var MODE_KEY = "tradinglab_mode";
  var mode = localStorage.getItem(MODE_KEY) || "meme";
  function $(id) { return document.getElementById(id); }
  function money(n) {
    var x = Number(n);
    if (!Number.isFinite(x)) return "—";
    var sign = x < 0 ? "-" : "";
    return sign + "$" + Math.abs(x).toFixed(2);
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
  function ensureShell() {
    document.body.classList.add("desk-unified");
    document.body.classList.toggle("mode-meme", mode === "meme");
    document.body.classList.toggle("mode-forex", mode === "forex");
    var host = $("command-deck") || document.body;
    if (!$("modeBar")) {
      var bar = document.createElement("div");
      bar.id = "modeBar";
      bar.innerHTML =
        '<button type="button" class="btn mode-btn" data-mode="meme">MEME</button>' +
        '<button type="button" class="btn mode-btn" data-mode="forex">FOREX</button>' +
        '<span class="hint" id="modeHint">One paper book per mode.</span>';
      var deckBd = host.querySelector(".secbd") || host;
      deckBd.insertBefore(bar, deckBd.firstChild);
      bar.querySelectorAll(".mode-btn").forEach(function (btn) {
        btn.addEventListener("click", function () { setMode(btn.getAttribute("data-mode")); });
      });
    }
    if (!$("unifiedStrip")) {
      var strip = document.createElement("div");
      strip.id = "unifiedStrip";
      strip.innerHTML =
        '<div class="cell"><div class="lab">Equity</div><div class="val" id="uEquity">—</div></div>' +
        '<div class="cell"><div class="lab">Cash</div><div class="val muted" id="uCash">—</div></div>' +
        '<div class="cell"><div class="lab">PnL</div><div class="val" id="uPnl">—</div></div>' +
        '<div class="cell"><div class="lab">Open</div><div class="val muted" id="uOpen">—</div></div>' +
        '<div class="cell"><div class="lab">Mode</div><div class="val muted" id="uMode">—</div></div>';
      var mb = $("modeBar");
      mb.parentNode.insertBefore(strip, mb.nextSibling);
    }
    if (!$("unifiedPositions")) {
      var box = document.createElement("div");
      box.id = "unifiedPositions";
      box.innerHTML =
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">' +
        "<strong>Positions</strong>" +
        '<span class="sub" id="uPosMeta" style="font-size:12px;color:#6a857a"></span></div>' +
        '<div id="uPosBody" class="empty">Loading…</div>';
      var stripEl = $("unifiedStrip");
      stripEl.parentNode.insertBefore(box, stripEl.nextSibling);
    }
    var paper = $("deckPaper");
    if (paper && !paper._unified) {
      paper._unified = true;
      paper.textContent = "Run cycle";
      paper.addEventListener("click", function () { setTimeout(refresh, 2500); });
    }
    paintModeButtons();
  }
  function paintModeButtons() {
    document.querySelectorAll("#modeBar .mode-btn").forEach(function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-mode") === mode);
    });
    var hint = $("modeHint");
    if (hint) {
      hint.textContent = mode === "meme"
        ? "Solana meme paper book · one equity · autonomous cycle"
        : "Forex paper book · chart still available below";
    }
    var um = $("uMode");
    if (um) um.textContent = mode === "meme" ? "MEME" : "FOREX";
    document.body.classList.toggle("mode-meme", mode === "meme");
    document.body.classList.toggle("mode-forex", mode === "forex");
  }
  function setMode(m) {
    mode = m === "forex" ? "forex" : "meme";
    localStorage.setItem(MODE_KEY, mode);
    paintModeButtons();
    refresh();
  }
  function paintBook(s) {
    var equity = Number(s.equity_usd != null ? s.equity_usd : s.equity);
    var cash = Number(s.cash_usd != null ? s.cash_usd : s.cash);
    var start = Number(s.initial_cash_usd != null ? s.initial_cash_usd : 1000);
    var realized = Number(s.realized_pnl_usd != null ? s.realized_pnl_usd : 0);
    var unreal = Number(s.unrealized_pnl_usd != null ? s.unrealized_pnl_usd : 0);
    var pnl = Number.isFinite(equity) && Number.isFinite(start) ? equity - start : realized + unreal;
    var openN = Number(s.open_positions_count != null ? s.open_positions_count : 0);
    var el;
    el = $("uEquity"); if (el) el.textContent = money(equity);
    el = $("uCash"); if (el) el.textContent = money(cash);
    el = $("uPnl");
    if (el) {
      el.textContent = (pnl >= 0 ? "+" : "") + money(pnl);
      el.className = "val " + (pnl >= 0 ? "" : "dn");
    }
    el = $("uOpen"); if (el) el.textContent = String(openN);
    el = $("deckBal"); if (el) el.textContent = money(equity);
    el = $("deckBalSub");
    if (el) el.textContent = "cash " + money(cash) + " · " + openN + " open";
    el = $("deckPnl");
    if (el) {
      el.textContent = (pnl >= 0 ? "+" : "") + money(pnl);
      el.className = "pnl-val " + (pnl >= 0 ? "up" : "dn");
    }
  }
  function paintPositions(list) {
    var body = $("uPosBody");
    var meta = $("uPosMeta");
    if (!body) return;
    list = Array.isArray(list) ? list : [];
    var open = list.filter(function (p) {
      var st = String(p.status || "OPEN").toUpperCase();
      return st === "OPEN" || st === "";
    });
    if (meta) meta.textContent = open.length + " open";
    if (!open.length) {
      body.innerHTML = '<div class="empty">No open positions in this book.</div>';
      return;
    }
    var rows = open.map(function (p) {
      var sym = p.symbol || p.pair || p.token_address || p.id || "?";
      var entry = p.entry_price != null ? p.entry_price : p.entry;
      var px = p.current_price != null ? p.current_price : p.price;
      var upnl = p.unrealized_pnl != null ? p.unrealized_pnl : p.upnl;
      return "<tr><td>" + String(sym).slice(0, 16) + '</td><td class="r">' + money(entry) +
        '</td><td class="r">' + money(px) + '</td><td class="r">' + money(upnl) + "</td></tr>";
    }).join("");
    body.innerHTML = '<table><thead><tr><th>Symbol</th><th class="r">Entry</th><th class="r">Mark</th><th class="r">uPnL</th></tr></thead><tbody>' +
      rows + "</tbody></table>";
  }
  async function refreshMeme() {
    try {
      try { await api("/api/meme/trader/tick", {}); } catch (_) {}
      var s = await api("/api/meme/trader");
      paintBook(s);
      paintPositions(s.positions || []);
      var st = $("memeTraderStatus");
      if (st) {
        st.innerHTML = '<div class="notes">Book synced above · realized ' + money(s.realized_pnl_usd) +
          " · daily loss " + money(s.daily_realized_loss_usd) + "</div>";
      }
    } catch (e) {
      var body = $("uPosBody");
      if (body) body.innerHTML = '<div class="empty">Meme book: ' + e.message + "</div>";
    }
  }
  async function refreshForex() {
    try {
      var s = await api("/api/forex");
      var acct = s.account || s;
      var equity = acct.equity != null ? acct.equity : acct.cash;
      var openList = s.positions || [];
      paintBook({
        equity_usd: equity,
        cash_usd: acct.cash,
        initial_cash_usd: acct.initial_cash || acct.starting_cash || 10000,
        realized_pnl_usd: acct.realized_pnl,
        open_positions_count: openList.filter(function (p) {
          return String(p.status || "OPEN").toUpperCase() === "OPEN";
        }).length
      });
      paintPositions(openList);
    } catch (e) {
      var body = $("uPosBody");
      if (body) body.innerHTML = '<div class="empty">Forex book: ' + e.message + "</div>";
    }
  }
  async function refresh() {
    ensureShell();
    if (mode === "forex") await refreshForex();
    else await refreshMeme();
  }
  function boot() {
    ensureShell();
    refresh();
    setInterval(refresh, 20000);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
  window.TradingLabUnified = { refresh: refresh, setMode: setMode };
})();
