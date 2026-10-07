# Memecoin paper-trading research lab

Ember is a local trading dashboard with a live $100 paper account, collaborating AI roles, real Pump.fun discovery through PumpPortal, deterministic token-risk rules and a separate Phantom-approved real-swap pilot. The overview charts saved paper capital, including modeled costs. Synthetic experiments are kept on the Research page.

Connect a model in **Connections & setup**, configure the paper trial, then inspect **Overview** and **Agent company**. For real swaps, connect Phantom and a Jupiter key, inspect a token and review the prepared transaction in **Wallet execution**. Real transactions require wallet approval; unattended real-money trading is not implemented. No model key or funded wallet has been configured or tested here.

The red-and-black interface has seven pages, responsive navigation, capital range controls and keyboard/hover observation inspection. Saved balances and history survive server restarts; entered API keys remain session-only.

**Update: AI team support is now available.** The original deterministic experiment remains available; the new Agent control room adds five collaborating LLM roles through OpenAI or local Ollama. A clearly labeled scripted workflow is provided for offline inspection. Read [AGENT-SETUP.md](AGENT-SETUP.md) for configuration, authority limits and inference-cost accounting. An AI provider has not yet been selected or activated.

**Live Pump.fun discovery is now available** through the third-party PumpPortal public creation/migration feed. Read [PUMP-DATA.md](PUMP-DATA.md). It records real events separately from the synthetic experiments; no wallet or paid stream is used.

## Run

Requires Python 3.10+; standard library only, no package installation or paid AI credentials.

```
cd outputs/trading-lab
python app.py
```

Open http://127.0.0.1:8765 and click **Run 120 observations**. Stop with Ctrl+C. On this Codex machine, if `python` is unavailable, run `./start.ps1` from this folder. Run tests with `python -m unittest -v` (or `./test.ps1`). The server binds to loopback only and is intended for one local user.

## Architecture and hypothesis

Scanner → screening → deterministic strategy → hard risk controller → paper execution → review. These are independent component roles, not autonomous LLM agents. The controller is the only admission path and enforces finite capital, fixed position allocation, position count, allocated exposure, stale entry rejection and a latched loss shutdown. Strategies cannot override controls. No capital increases, leverage or self-modification exist. Setting edits create new experiments; proposed strategy revisions require separate evaluation.

Unproven hypothesis v1: at least $100,000 pool liquidity and age 24 hours; a 3% rise across five past one-minute intervals triggers entry. Fill occurs at least one subsequent observation later. Exit at 8% gain, 5% loss or 12-observation holding time. All defaults are illustrative, not financial recommendations. Risk default: $1,000 capital, $100 positions, at most three positions / 30% allocated exposure, 10% loss shutdown. Gaps, missing routes and fees can exceed the shutdown threshold; it is not a guaranteed maximum loss.

The baseline enters every eligible token without the momentum signal, uses the same admission controls, delays and costs, and exits after the same holding limit. Both are independent portfolios with equal initial capital. It is a constrained periodic holding baseline, not an optimized competitor.

## Accounting and failures

Costs per side: configurable fee + adverse slippage + approximate size impact using pool liquidity. Fees are included in fills; network charges occur per fill; operating charges occur per observation, limited to available cash. Exhausting the operating budget latches shutdown. Equity and net P&L include conservative estimated liquidation costs on open positions. Both buy and exit signals use delayed observations; triggered exits remain pending across route failures. There are no actual executable quotes in synthetic fills. Trading fees are not separately totaled, but fill prices and proceeds are logged. Allocation exposure uses entry capital, not changing market value; liquidation equity is reported separately.

Missing data clears momentum history. Stale entries are rejected. Missing, stale or failed exit routes retain positions and log failed exits at each observation. Their liquidation value is zero until a fresh route returns. Loss shutdown latches and attempts exits at every subsequent fresh observation. End-of-run positions are retained rather than pretending forced exits succeeded. Synthetic scenarios include a disappearance, liquidity rejection, a data outage and temporary exit failure.

## Data, persistence and evaluation

`lab.sqlite` stores complete run settings/results, per-observation candidate/rejection/decision logs and raw live observation captures. Export complete run JSON from the dashboard. Synthetic time is elapsed seconds from t+0; run records have real UTC epoch creation times. Development and evaluation use distinct fixed seeds; no future frames are accessed for signals, and the no-look-ahead test checks prefix invariance. The initial universe retains missing/disappearing tokens instead of filtering survivors.

Synthetic evaluation is a mechanics check only. Before real research, freeze the hypothesis/settings in a preregistered run; prospectively capture a broad point-in-time token universe, source timestamps, token safety evidence, liquidity, fees, failure events and executable quotes. Split real data chronologically with an embargo at least as long as lookback + maximum holding + latency. Do not tune on evaluation results; repeated use converts the holdout to development data. Include abandoned/delisted pools and failed observations, not only currently listed winners. Compare returns, drawdown, turnover, fill coverage, failures and cost sensitivity against the baseline across multiple regimes; require uncertainty intervals before any edge claim.

## Read-only integrations

Official documentation inspected on 2026-10-06:

- DEX Screener: https://docs.dexscreener.com/api/reference — GET `/token-pairs/v1/solana/{mint}`, documented 300 requests/minute. Manual dashboard captures are watchlist observations, not comprehensive discovery. No background polling. Fetch time does not certify source freshness. Unknown token authorities, holder concentration or malicious transfer behavior are not certified safe; live paper trading is deliberately gated off until these checks exist.
- Jupiter: https://developers.jup.ag/docs/api-reference/swap/v1/quote — GET quote with input/output mint and raw integer amounts; API key required at `api.jup.ag`. Current docs mark V1 superseded by V2. Optional compatibility quote adapter uses V1 and fails closed on API errors. It never builds or submits a transaction. Upgrade and validate it before using quotes for prospective evaluation.

Optional CLI: set `JUPITER_API_KEY` in your environment and run `python app.py --quote SOLANA_MINT`. It records an indicative $10 USDC buy quote and reverse sell quote for the returned raw token amount. Raw route fees, slippage threshold and context slot remain in the saved response. Quote requests are sequential, not simultaneous; they are not guaranteed executable or guaranteed profitable. Token decimals are unnecessary for raw-amount round trips. No fallback to fabricated quotes. Network failures appear as errors; synthetic runs remain available offline.

## Scope and next work

MVP includes working agents, local dashboard, two-sided indicative quote tool, deterministic tests, durable local logs and synthetic failure simulation. It does not include live universe discovery, token authority/security analysis, true chain latency/MEV simulation, historical real-data replay, statistical edge validation or production multi-user authentication. Those are prerequisites for trustworthy live paper evaluation. AI interpretation is optional future work and must never bypass the controller. No deployment was performed.

Continuous live-data paper trial: see LIVE-PAPER.md. Fixed initial simulated capital is 100 dollars; actual AI entries require a configured provider. This is separate from synthetic runs and live discovery alone.

**Quote-based paper execution:** The live trial now uses conservative read-only Jupiter quotes for new paper fills and usage-priced model costs. Existing history stays intact; arbitrary observation charges stop prospectively. Configure a Jupiter key and exact model token prices to activate this path. Infrastructure and actual chain costs remain unmeasured, and quote fills are hypothetical. See [QUOTE-PAPER.md](QUOTE-PAPER.md).

Performance and learning workflows: see [PERFORMANCE.md](PERFORMANCE.md).


## Company OS upgrade

The bounded virtual-company layer is now implemented in `company_os.py`. It adds executive work orchestration, persistent company memory, research hypotheses/experiments, independent evaluation, audit findings and resource budgets while preserving the existing deterministic controller as the only execution authority. See [COMPANY-ARCHITECTURE.md](COMPANY-ARCHITECTURE.md). Run the focused tests with `python -m unittest -v test_company_os.py`.
