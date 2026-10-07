# Verification

Verified on 2026-10-06 with bundled Python 3 runtime, standard library only.

## AI team update

- Added five independently prompted AI roles with sequential handoffs, unanimous entry approval, optional early exits, hard external risk controls, finite round budgets and configurable inference-cost estimates.
- OpenAI Responses and local Ollama adapters implemented from official documentation. Actual provider calls are not verified or activated; the user chose to select a provider later.
- All 20 tests passed, including offline provider/request-shape, collaboration, cancellation during a call and forced loss-shutdown checks. The browser scripted workflow completed three rounds / fifteen role calls, produced 34 persistent handoff/review records, rendered agent status cards and saved its paper result. Start button re-enabled on completion.
- Scripted responses are labeled as non-AI. No paid inference, live execution or wallet integration occurred.

## Pump.fun discovery update

- All 25 tests passed, including mint validation, null/invalid numeric handling, real-vs-synthetic provenance, migration normalization, durable raw-event persistence and deduplication.
- A public PumpPortal WebSocket without an API key connected successfully outside the network-restricted sandbox. Both token-creation and migration subscriptions were acknowledged. Actual live discovery events were received and saved in SQLite; there is no synthetic fallback.
- The dashboard showed the collector connected and rendered real token rows. The source is labeled third-party PumpPortal, receive timestamps are labeled local, and market cap is labeled in SOL rather than USD or executable liquidity.

- Ten unit tests passed: deterministic replay, distinct data partitions, prefix invariance/no future access, latched shutdown, capital/exposure constraints, delayed entries and exits, unavailable exit retention, stale entry rejection, cost sensitivity, durable SQLite persistence and invalid-settings rejection.
- Local server started successfully on 127.0.0.1:8765.
- Browser main flow verified: default development run saved successfully, metrics and equity curves rendered, baseline comparison and timestamped decisions displayed; export enabled.
- Synthetic development test run triggered risk shutdown during a temporary failed exit route; returned routes did not unlock the shutdown. This is simulated behavior, not market evidence.
- Dashboard preview saved in ../dashboard-preview.jpg.
- Saved run reopening and invalid-setting HTTP rejection verified.
- Live Jupiter quotes require an optional API key and were not tested against the authenticated service. A DEX Screener read-only request was attempted; this environment blocked outbound sockets (Windows error 10013), and the interface returned an explicit error. The adapter follows official documentation but successful live connectivity is unverified. Failed captures are persisted. No real-market performance evaluation occurred.

## Continuous live paper trial (2026-10-07)
33 tests passed. The server returned the live trial controls and HTTP state successfully. Started a persistent initial 100-dollar simulated portfolio in observation mode, recorded actual public market API responses, verified pause preserved state, and verified restart automatically resumed the enabled worker without resetting cash. AI provider remains unconfigured; no paid AI calls or real transactions occurred. Current discovery samples may have no usable/eligible pools; empty responses are retained rather than fabricated. Browser visual automation was blocked by the environment sandbox helper; dashboard script syntax and HTTP flow were verified. See LIVE-PAPER.md.

## Product dashboard polish (2026-10-07)
69 backend tests passed, including durable capital-history filtering and chronology after reopening SQLite. Main and product JavaScript syntax checks passed. A real headless Chrome check visited all seven routes, verified the one-hour capital range, observation inspection, two chart series, no duplicate IDs and no runtime exceptions. Desktop and 500px mobile previews were inspected; setup and company pages were inspected separately. Asset endpoints returned HTTP 200; live history contained 127 saved genuine paper valuations at verification time. No paid model calls, wallet approvals or real trades were performed. Preview files: ../ember-desktop.png, ../ember-mobile.png, ../ember-settings.png and ../ember-agents.png.

## Quote paper / accounting upgrade (2026-10-07)
83 tests passed. Tests include durable AI reserve settlement from reported usage, unresolved/interrupted-call abstention and conservative quote failure handling. Browser navigation and chart checks passed after adding pricing controls. A server transition preserved strategy equity 99.30500000000063 and historical charges 0.6950000000000005 exactly, with 140 recorded valuations retained. Version 2 stopped future arbitrary observation charges and exposed missing Jupiter configuration as a blocker. No model or quote credentials were configured; authenticated provider calls remain unverified. See QUOTE-PAPER.md.

## Operations update (2026-10-07)
91 backend tests passed. Real Chrome checks confirmed all seven routes, nine checklist rows, three comparison accounts, 19 existing journal records, no duplicate IDs and no runtime exceptions. Desktop overview and office previews were inspected. See OPERATIONS.md for notification limitations, prospective comparison boundaries and decision-journal scope. Existing account balances and histories were retained; fixed rules started prospectively at $100. No API credentials or real trades were used.

## Virtual company (2026-10-07)
96 backend tests passed. Chrome verified ten role cards, four capital metrics, company policy fields and persistent assigned work orders; no runtime errors or duplicate IDs. Headquarters preview inspected. See VIRTUAL-COMPANY.md for daily-budget boundaries and role authority. No model keys, paid inference or real transactions were used.

## Performance and learning (2026-10-07)
125 backend checks passed. Chrome verified seven routes, owner briefing, matched laboratory, learning review, market evidence and execution audit with no runtime exceptions or duplicate IDs. Desktop and 390px mobile screenshots inspected; no horizontal overflow. New matched accounts collected prospective public-data observations. Existing balances retained. No credentials, paid inference or real transactions used. See PERFORMANCE.md.
