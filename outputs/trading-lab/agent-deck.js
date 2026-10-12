/* TradingLab · Command Deck — six-agent deliberation UI (2029) */
(function () {
  const AGENTS = [
    { key: "market", name: "Market Observer", short: "01", role: "Data quality" },
    { key: "technical", name: "Technical Analyst", short: "02", role: "Structure" },
    { key: "macro", name: "Macro / Narrative", short: "03", role: "Regime" },
    { key: "strategy", name: "Strategy Proposer", short: "04", role: "Hypotheses" },
    { key: "risk", name: "Risk Critic", short: "05", role: "Adversarial" },
    { key: "coordinator", name: "Portfolio Coord", short: "06", role: "Final call" },
  ];

  function $(id) { return document.getElementById(id); }

  function renderStations() {
    const grid = $("agentGrid");
    if (!grid) return;
    grid.innerHTML = AGENTS.map(a => `
      <div class="agent-card" data-key="${a.key}" id="ac-${a.key}">
        <div class="ring">${a.short}</div>
        <div class="aname">${a.name}</div>
        <div class="arole">${a.role}</div>
        <div class="astatus" id="as-${a.key}">STANDBY</div>
      </div>`).join("");
  }

  function setAgentState(key, state) {
    const card = $("ac-" + key);
    const st = $("as-" + key);
    if (!card || !st) return;
    card.classList.remove("active", "speaking");
    if (state === "speaking") {
      card.classList.add("speaking");
      st.textContent = "SPEAKING";
    } else if (state === "done") {
      card.classList.add("active");
      st.textContent = "REPORT FILED";
    } else if (state === "error") {
      st.textContent = "FAULT";
    } else {
      st.textContent = "STANDBY";
    }
  }

  function termAppend(html) {
    const body = $("termBody");
    if (!body) return;
    const empty = body.querySelector(".term-empty");
    if (empty) empty.remove();
    body.insertAdjacentHTML("beforeend", html);
    const screen = $("termScreen");
    if (screen) screen.scrollTop = screen.scrollHeight;
  }

  function termBoot(mode) {
    const body = $("termBody");
    if (!body) return;
    body.innerHTML = "";
    const lines = [
      "TRADINGLAB AGENT COMPANY · KERNEL 2029.10",
      "MODE=" + mode.toUpperCase() + " · PAPER_ONLY=TRUE · EXECUTION=DISABLED",
      "Loading specialist stations…",
      "Risk interlock online. Daily-loss circuit armed.",
      "---",
    ];
    lines.forEach((l, i) => {
      setTimeout(() => {
        termAppend(`<div class="boot-line ${i > 2 ? "ok" : ""}">${l}</div>`);
      }, i * 90);
    });
  }

  function formatReport(report) {
    if (!report || typeof report !== "object") return "(no payload)";
    const parts = [];
    for (const [k, v] of Object.entries(report)) {
      if (k === "concerns" || k === "veto_reasons") continue;
      if (Array.isArray(v)) parts.push(k + ": " + v.slice(0, 4).join("; "));
      else if (v != null && String(v).trim()) parts.push(k + ": " + String(v));
    }
    const concerns = report.concerns || report.veto_reasons || [];
    if (concerns.length) parts.push("concerns: " + concerns.slice(0, 4).join("; "));
    return parts.join("\n") || "(empty report)";
  }

  function paintDecision(final) {
    const box = $("decisionBox");
    if (!box || !final) return;
    const side = (final.side || final.decision || "hold").toLowerCase();
    let cls = "hold";
    if (side === "buy" || side === "long") cls = "buy";
    else if (side === "sell" || side === "short") cls = "sell";
    box.innerHTML = `
      <div class="label">COORDINATOR DECISION</div>
      <div class="val ${cls}">${(final.decision || side || "HOLD").toUpperCase()}</div>
      <div class="rationale">${final.rationale || "—"}</div>
      <div style="margin-top:10px;font-size:10px;color:#6b7a88">
        ${final.pair_or_token ? "Instrument: <b style='color:#c8d4e0'>" + final.pair_or_token + "</b>" : "No instrument named"}
        ${final.size_hint ? " · Size hint: " + final.size_hint : ""}
      </div>`;
  }

  async function runDeliberation(kind) {
    const fxBtn = $("deckFx");
    const memeBtn = $("deckMeme");
    if (fxBtn) fxBtn.disabled = true;
    if (memeBtn) memeBtn.disabled = true;
    AGENTS.forEach(a => setAgentState(a.key, "idle"));
    termBoot(kind === "meme" ? "solana_meme" : "forex");
    $("deckStatus").textContent = "DELIBERATING…";
    $("deckStatus").className = "gate-chip";

    const endpoint = kind === "meme"
      ? "/api/meme/trader/deliberate"
      : "/api/forex/agents/deliberate";
    const body = kind === "meme"
      ? { limit: 20, apply_paper: false }
      : { apply_paper: false };

    try {
      let i = 0;
      const pulse = setInterval(() => {
        if (i > 0) setAgentState(AGENTS[i - 1].key, "done");
        if (i < AGENTS.length) {
          setAgentState(AGENTS[i].key, "speaking");
          i++;
        } else clearInterval(pulse);
      }, 420);

      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      clearInterval(pulse);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.statusText);

      const delib = data.deliberation || data;
      const agents = delib.agents || [];
      AGENTS.forEach(a => setAgentState(a.key, "idle"));

      for (const rec of agents) {
        const key = rec.key || "market";
        setAgentState(key, "speaking");
        await new Promise(r => setTimeout(r, 180));
        const cls = key === "risk" ? "risk" : key === "coordinator" ? "coord" : "agent";
        const ok = rec.ok !== false;
        termAppend(`
          <div class="term-line ${cls}">
            <div class="who">${(rec.agent || key).toUpperCase()}${ok ? "" : " · FAULT"}</div>
            <div class="body">${formatReport(rec.report)}${rec.error ? "\n" + rec.error : ""}</div>
            <div class="meta">${ok ? "advisory · does not execute" : "fallback hold"}</div>
          </div>`);
        setAgentState(key, ok ? "done" : "error");
        await new Promise(r => setTimeout(r, 120));
      }

      const final = delib.final_decision || {};
      paintDecision(final);
      termAppend(`
        <div class="term-line coord">
          <div class="who">SYSTEM</div>
          <div class="body">Cycle ${delib.cycle_id || "—"} complete · ${delib.duration_seconds || "?"}s · paper_only</div>
          <div class="meta">Deterministic risk engine remains final authority</div>
        </div>
        <span class="term-cursor"></span>`);

      $("deckStatus").textContent = "CYCLE COMPLETE · PAPER ONLY";
      $("deckStatus").className = "gate-chip";
      if (typeof say === "function") {
        say("Six-agent deliberation finished. Advisory only — no live order.", "ok");
      }
      if (typeof refresh === "function") await refresh();
      if (kind === "meme" && typeof loadMemeTrader === "function") await loadMemeTrader();
    } catch (e) {
      termAppend(`<div class="term-line risk"><div class="who">SYSTEM FAULT</div><div class="body">${e.message}</div></div>`);
      $("deckStatus").textContent = "FAULT";
      $("deckStatus").className = "gate-chip warn";
      if (typeof say === "function") say(e.message, "bad");
    } finally {
      if (fxBtn) fxBtn.disabled = false;
      if (memeBtn) memeBtn.disabled = false;
    }
  }

  function init() {
    document.body.classList.add("t2029");
    renderStations();
    const fx = $("deckFx");
    const meme = $("deckMeme");
    if (fx) fx.addEventListener("click", () => runDeliberation("forex"));
    if (meme) meme.addEventListener("click", () => runDeliberation("meme"));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.TradingLabDeck = { runDeliberation, renderStations };
})();
