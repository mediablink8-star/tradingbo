/* TradingLab · Command Deck
   Functional six-agent floor + paper PnL dashboard.
   Matches Grok Bot demo layout; stays paper-only. */
(function () {
  "use strict";

  const AGENTS = [
    { key: "market",      name: "Observer",   short: "OBS", role: "Market data" },
    { key: "technical",   name: "Technical",  short: "TEC", role: "Structure" },
    { key: "macro",       name: "Narrative",  short: "NAR", role: "Regime" },
    { key: "strategy",    name: "Strategy",   short: "STR", role: "Hypotheses" },
    { key: "risk",        name: "Risk Critic",short: "RSK", role: "Veto power" },
    { key: "coordinator", name: "Coordinator",short: "CRD", role: "Final call" },
  ];

  const history = []; // {t, equity}
  let tasks = 0;
  let combo = 1;
  let logCount = 0;

  function $(id) { return document.getElementById(id); }

  function money(n) {
    const x = Number(n);
    if (!Number.isFinite(x)) return "—";
    const sign = x < 0 ? "-" : "";
    return sign + "$" + Math.abs(x).toLocaleString(undefined, {
      minimumFractionDigits: 2, maximumFractionDigits: 2
    });
  }

  function pct(n) {
    const x = Number(n);
    if (!Number.isFinite(x)) return "—";
    return (x >= 0 ? "+" : "") + x.toFixed(1) + "%";
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function renderStations() {
    const grid = $("agentGrid");
    if (!grid) return;
    grid.innerHTML = AGENTS.map((a, i) => `
      <div class="acard" data-agent="${a.key}" id="acard-${a.key}">
        <div class="ring">${a.short}</div>
        <div class="aname">${esc(a.name)}</div>
        <div class="arole">${esc(a.role)}</div>
        <div class="abal" id="abal-${a.key}">$0.00</div>
        <div class="astatus" id="astat-${a.key}">IDLE</div>
      </div>`).join("");
  }

  function setAgentState(key, state) {
    const card = $("acard-" + key);
    const st = $("astat-" + key);
    if (!card) return;
    card.classList.remove("active", "speaking");
    if (state === "speaking") {
      card.classList.add("speaking");
      if (st) st.textContent = "SPEAKING";
    } else if (state === "done") {
      card.classList.add("active");
      if (st) st.textContent = "DONE";
    } else if (state === "error") {
      if (st) st.textContent = "FAULT";
    } else if (state === "active") {
      card.classList.add("active");
      if (st) st.textContent = "LIVE";
    } else {
      if (st) st.textContent = "IDLE";
    }
  }

  function resetAgents() {
    AGENTS.forEach(a => setAgentState(a.key, "idle"));
  }

  function logLine(tag, text, cls) {
    const box = $("deckLog");
    if (!box) return;
    logCount += 1;
    const row = document.createElement("div");
    row.className = "log-row";
    row.innerHTML =
      `<span class="log-tag ${cls || tag.toLowerCase()}">[${esc(tag)}]</span>` +
      `<span class="log-txt">${text}</span>`;
    box.prepend(row);
    while (box.children.length > 80) box.removeChild(box.lastChild);
    const c = $("deckLogCount");
    if (c) c.textContent = logCount + " resolved";
  }

  function termClear(bootMsg) {
    const body = $("termBody");
    if (!body) return;
    body.innerHTML = bootMsg
      ? `<div class="boot-line ok">${esc(bootMsg)}</div>`
      : "";
  }

  function termAppend(html) {
    const body = $("termBody");
    if (!body) return;
    const empty = body.querySelector(".term-empty");
    if (empty) empty.remove();
    body.insertAdjacentHTML("beforeend", html);
    body.scrollTop = body.scrollHeight;
  }

  function formatReport(report) {
    if (report == null) return "—";
    if (typeof report === "string") return esc(report);
    try {
      return esc(JSON.stringify(report, null, 2));
    } catch (_) {
      return esc(String(report));
    }
  }

  function paintDecision(final) {
    const box = $("decisionBox");
    if (!box) return;
    const action = String((final && (final.action || final.decision || final.preferred_action)) || "hold").toLowerCase();
    const rationale = (final && (final.rationale || final.reason || final.summary)) || "No rationale returned.";
    let cls = "hold";
    if (/buy|long|open/.test(action)) cls = "buy";
    else if (/sell|short|close/.test(action)) cls = "sell";
    box.innerHTML =
      `<div class="label">COORDINATOR DECISION</div>` +
      `<div class="val ${cls}">${esc(action.toUpperCase())}</div>` +
      `<div class="rationale">${esc(String(rationale).slice(0, 420))}</div>`;
  }

  function pushHistory(equity) {
    const e = Number(equity);
    if (!Number.isFinite(e)) return;
    history.push({ t: Date.now(), equity: e });
    if (history.length > 120) history.shift();
    drawChart();
  }

  function drawChart() {
    const canvas = $("deckChart");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || 640;
    const h = 220;
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    ctx.strokeStyle = "rgba(0,245,160,0.06)";
    ctx.lineWidth = 1;
    for (let i = 0; i < 5; i++) {
      const y = 20 + (h - 40) * (i / 4);
      ctx.beginPath(); ctx.moveTo(12, y); ctx.lineTo(w - 12, y); ctx.stroke();
    }

    if (history.length < 2) {
      ctx.fillStyle = "#3a4a55";
      ctx.font = "11px JetBrains Mono, monospace";
      ctx.fillText("Equity trail appears after paper cycles.", 16, h / 2);
      return;
    }

    let min = Infinity, max = -Infinity;
    history.forEach(p => {
      min = Math.min(min, p.equity);
      max = Math.max(max, p.equity);
    });
    if (max - min < 1) { min -= 1; max += 1; }
    const pad = (max - min) * 0.08;
    min -= pad; max += pad;

    const xs = (i) => 16 + (w - 32) * (i / (history.length - 1));
    const ys = (v) => 16 + (h - 32) * (1 - (v - min) / (max - min));

    const grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, "rgba(0,245,160,0.25)");
    grad.addColorStop(1, "rgba(0,245,160,0.0)");
    ctx.beginPath();
    history.forEach((p, i) => {
      const x = xs(i), y = ys(p.equity);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.lineTo(xs(history.length - 1), h - 16);
    ctx.lineTo(xs(0), h - 16);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    ctx.beginPath();
    history.forEach((p, i) => {
      const x = xs(i), y = ys(p.equity);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = "#00f5a0";
    ctx.lineWidth = 2;
    ctx.shadowColor = "rgba(0,245,160,0.55)";
    ctx.shadowBlur = 8;
    ctx.stroke();
    ctx.shadowBlur = 0;

    const last = history[history.length - 1];
    const lx = xs(history.length - 1), ly = ys(last.equity);
    ctx.beginPath();
    ctx.arc(lx, ly, 4, 0, Math.PI * 2);
    ctx.fillStyle = "#e8fff6";
    ctx.fill();
  }

  function paintStatus(s) {
    if (!s || typeof s !== "object") return;
    const equity = Number(s.equity_usd != null ? s.equity_usd : s.equity);
    const cash = Number(s.cash_usd != null ? s.cash_usd : s.cash);
    const realized = Number(s.realized_pnl != null ? s.realized_pnl : 0);
    const openN = Number(s.open_positions_count != null ? s.open_positions_count : 0);

    if (Number.isFinite(equity)) {
      $("deckBal") && ($("deckBal").textContent = money(equity));
      pushHistory(equity);
    }
    const start = Number(s.starting_cash_usd != null ? s.starting_cash_usd :
      (Number.isFinite(cash) && Number.isFinite(realized) ? cash - realized : NaN));
    let pnl = Number.isFinite(equity) && Number.isFinite(start) ? equity - start : realized;
    const pnlEl = $("deckPnl");
    if (pnlEl && Number.isFinite(pnl)) {
      pnlEl.textContent = (pnl >= 0 ? "+" : "") + money(pnl).replace("$", "$");
      pnlEl.className = "pnl-val " + (pnl >= 0 ? "up" : "dn");
    }
    if ($("deckBalSub")) {
      $("deckBalSub").textContent =
        (Number.isFinite(cash) ? "cash " + money(cash) : "paper equity") +
        " · " + openN + " open";
    }

    const positions = Array.isArray(s.positions) ? s.positions : [];
    const closed = positions.filter(p => String(p.status || "").toUpperCase() === "CLOSED");
    const wins = closed.filter(p => Number(p.realized_pnl) > 0);
    if (closed.length && $("deckWin")) {
      const rate = Math.round((wins.length / closed.length) * 100);
      $("deckWin").textContent = rate + "%";
      if ($("deckWinSub")) $("deckWinSub").textContent = wins.length + "W / " + closed.length + " closed";
    }
    if (closed.length) {
      let best = null;
      closed.forEach(p => {
        const r = Number(p.realized_pnl);
        if (!Number.isFinite(r)) return;
        if (!best || r > Number(best.realized_pnl)) best = p;
      });
      if (best && $("deckBig")) {
        $("deckBig").textContent = money(best.realized_pnl);
        if ($("deckBigSub")) {
          $("deckBigSub").textContent =
            (best.symbol || best.token_address || "trade") + " · closed";
        }
      }
    }

    if (Number.isFinite(equity) && equity > 0) {
      const weights = [0.22, 0.18, 0.17, 0.16, 0.15, 0.12];
      AGENTS.forEach((a, i) => {
        const el = $("abal-" + a.key);
        if (el) el.textContent = money(equity * weights[i]);
      });
    }
  }

  async function api(path, opts) {
    const r = await fetch(path, opts || {});
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || r.statusText || "request failed");
    return j;
  }

  async function refreshStatus() {
    try {
      const s = await api("/api/meme/trader");
      paintStatus(s);
      if (s.deliberation_available) {
        $("deckLive") && ($("deckLive").textContent = "LIVE");
      }
    } catch (_) { /* quiet */ }
  }

  function bumpTasks(n) {
    tasks += n || 1;
    if ($("deckTasks")) $("deckTasks").textContent = tasks.toLocaleString() + " TASKS";
  }

  function bumpCombo() {
    combo = Math.min(combo + 1, 12);
    if ($("deckCombo")) $("deckCombo").textContent = "COMBO ×" + combo;
  }

  async function runPaperCycle() {
    const btn = $("deckPaper");
    if (btn) btn.disabled = true;
    $("deckStatus") && ($("deckStatus").textContent = "PAPER CYCLE…");
    logLine("SCAN", "Starting deterministic meme paper cycle…", "scan");
    try {
      const r = await api("/api/meme/trader/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit: 30 })
      });
      bumpTasks(8);
      const scan = r.scan || {};
      logLine("SCAN",
        `discovered ${scan.discovered_tokens || 0} · scored ${scan.scored_candidates || 0} · watch ${scan.watchlist_count || 0}`,
        "scan");
      const decisions = ((r.cycle || {}).decisions) || [];
      decisions.forEach(d => {
        const act = String(d.action || d.reason || "hold").toUpperCase();
        const sym = d.symbol || d.name || d.token_address || "pair";
        if (/BUY|OPEN/.test(act)) {
          logLine("EXEC", `<b>BUY</b> ${esc(sym)} · ${esc(d.reason || "gate passed")}`, "exec");
          bumpCombo();
        } else if (/SELL|CLOSE/.test(act)) {
          logLine("FILL", `<b>SELL</b> ${esc(sym)} · ${esc(d.reason || "exit")}`, "fill");
        } else {
          logLine("RISK", `${esc(sym)} · ${esc(d.reason || act)}`, "risk");
        }
      });
      if (r.status) paintStatus(r.status);
      else await refreshStatus();
      $("deckStatus") && ($("deckStatus").textContent = "PAPER CYCLE DONE");
      if (typeof say === "function") say("Paper cycle finished. Still no live orders.", "ok");
    } catch (e) {
      logLine("WARN", esc(e.message), "warn");
      $("deckStatus") && ($("deckStatus").textContent = "FAULT");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function runDeliberation(kind) {
    const fxBtn = $("deckFx");
    const memeBtn = $("deckMeme");
    if (fxBtn) fxBtn.disabled = true;
    if (memeBtn) memeBtn.disabled = true;
    resetAgents();
    termClear("Opening floor · six agents · paper only");
    $("deckStatus") && ($("deckStatus").textContent = "DELIBERATING…");
    $("deckLive") && ($("deckLive").textContent = "LIVE");
    logLine("SCAN", `Six-agent ${kind} deliberation requested`, "scan");

    const endpoint = kind === "meme"
      ? "/api/meme/trader/deliberate"
      : "/api/forex/agents/deliberate";
    const body = kind === "meme"
      ? { limit: 20, apply_paper: true }
      : { apply_paper: true };

    try {
      const r = await api(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      bumpTasks(12);
      const delib = r.deliberation || r;
      const agents = delib.conversation || delib.agents || delib.stages || [];

      if (!agents.length && delib.error) {
        throw new Error(delib.error);
      }
      if (!agents.length) {
        termAppend(`<div class="term-line agent"><div class="who">SYSTEM</div><div class="body">${formatReport(delib)}</div></div>`);
      }

      for (const rec of agents) {
        const key = rec.key || rec.agent_key ||
          (String(rec.agent || "").toLowerCase().includes("risk") ? "risk" :
           String(rec.agent || "").toLowerCase().includes("coord") ? "coordinator" :
           String(rec.agent || "").toLowerCase().includes("tech") ? "technical" :
           String(rec.agent || "").toLowerCase().includes("macro") || String(rec.agent || "").toLowerCase().includes("narr") ? "macro" :
           String(rec.agent || "").toLowerCase().includes("strat") ? "strategy" : "market");
        setAgentState(key, "speaking");
        await new Promise(res => setTimeout(res, 160));
        const cls = key === "risk" ? "risk" : key === "coordinator" ? "coord" : "agent";
        const ok = rec.ok !== false;
        termAppend(`
          <div class="term-line ${cls}">
            <div class="who">${esc((rec.agent || key).toUpperCase())}${ok ? "" : " · FAULT"}</div>
            <div class="body">${formatReport(rec.report || rec.text || rec.content || rec)}</div>
            <div class="meta">${ok ? "advisory · does not execute" : "fallback"}</div>
          </div>`);
        setAgentState(key, ok ? "done" : "error");
        logLine(ok ? "FILL" : "WARN",
          `${esc(rec.agent || key)} spoke`,
          ok ? "fill" : "warn");
        await new Promise(res => setTimeout(res, 90));
      }

      const final = delib.final_decision || delib.decision || r.decision || {};
      paintDecision(final);
      if (final && (final.action || final.decision)) {
        logLine("MEGA",
          `Coordinator → <b>${esc(String(final.action || final.decision).toUpperCase())}</b>`,
          "mega");
        bumpCombo();
      }

      if (r.paper || r.status || kind === "meme") {
        if (r.status) paintStatus(r.status);
        else if (r.paper && r.paper.status) paintStatus(r.paper.status);
        else await refreshStatus();
      }

      termAppend(`
        <div class="term-line coord">
          <div class="who">SYSTEM</div>
          <div class="body">Cycle ${esc(delib.cycle_id || "—")} complete · paper_only</div>
          <div class="meta">Risk engine remains final authority · no wallet</div>
        </div>
        <span class="term-cursor"></span>`);

      $("deckStatus") && ($("deckStatus").textContent = "CYCLE COMPLETE · PAPER ONLY");
      if (typeof say === "function") say("Six-agent deliberation finished. Paper only.", "ok");
      if (typeof refresh === "function") await refresh();
      if (kind === "meme" && typeof loadMemeTrader === "function") await loadMemeTrader();
    } catch (e) {
      termAppend(`<div class="term-line risk"><div class="who">SYSTEM FAULT</div><div class="body">${esc(e.message)}</div></div>`);
      logLine("WARN", esc(e.message), "warn");
      $("deckStatus") && ($("deckStatus").textContent = "FAULT");
      if (typeof say === "function") say(e.message, "bad");
    } finally {
      if (fxBtn) fxBtn.disabled = false;
      if (memeBtn) memeBtn.disabled = false;
    }
  }

  function init() {
    document.body.classList.add("t2029");
    renderStations();
    drawChart();
    refreshStatus();
    setInterval(refreshStatus, 20000);

    const fx = $("deckFx");
    const meme = $("deckMeme");
    const paper = $("deckPaper");
    if (fx) fx.addEventListener("click", () => runDeliberation("forex"));
    if (meme) meme.addEventListener("click", () => runDeliberation("meme"));
    if (paper) paper.addEventListener("click", runPaperCycle);

    window.addEventListener("resize", drawChart);
    logLine("SCAN", "Command Deck online · paper mode · risk engine armed", "scan");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.TradingLabDeck = { runDeliberation, runPaperCycle, renderStations, refreshStatus };
})();
