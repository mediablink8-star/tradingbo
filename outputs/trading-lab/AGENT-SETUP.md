# Collaborating AI agents

The dashboard now has an **Agent control room**. Start bounded paper autopilot to see team handoffs, reports, approvals, vetoes and estimated inference costs. It replays synthetic observations, not real coins or real time.

Five independently prompted LLM roles work sequentially: market researcher, token screener, strategy analyst, risk critic, portfolio coordinator. Each reads the supplied point-in-time evidence and earlier reports. These are separate role calls to one configured model, not five independent services or trained models. Entry requires the intersection of all five approvals, the fixed momentum hypothesis, and hard risk checks at execution. AI can request early paper exits but cannot cancel mandatory exits. The performance reviewer is a deterministic accounting component, explicitly labeled as such in its report.

The AI layer adds discretion to the paper experiment; it does not replace the scanner, screening minimums, strategy envelope or risk controller. No model has wallet access, arbitrary tools, network tools, code execution or the ability to change configuration. Nothing here signs or sends real transactions. Real-wallet integration and user-signed trades are not implemented in this update.

## Provider choices

**Scripted workflow demo:** immediately available without accounts. Every report is explicitly labeled SCRIPTED DEMO. No AI is called; use it to check the handoff interface.

**Local Ollama:** use an already-installed Ollama instance serving `http://127.0.0.1:11434`. Select Local AI and enter the exact name of a model you have downloaded. The adapter calls `/api/chat` with JSON schema format and non-streaming responses. No service was installed or model downloaded for you. Model compatibility and successful actual inference remain unverified.

**OpenAI:** configure `OPENAI_API_KEY` in the environment of the process that launches the server, restart it, select OpenAI, and enter an accessible model name supporting Responses structured output. Do not paste keys into chat or the dashboard. The server calls only `https://api.openai.com/v1/responses`, with `store:false`, structured JSON output and a 1,200-token output limit. It passes synthetic observations, settings and prior agent reports to the provider. The dashboard never receives the key. No model is preselected and no paid call has been made.

Official references checked during implementation: [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses) and [Ollama chat API](https://docs.ollama.com/api/chat).

## Bounded operation and accounting

One active team per server, 1–12 rounds, five calls per round, at most 60 attempted calls. Reviews occur every ten synthetic observations once candidates or positions exist. Default three rounds. Each model request has a 45-second timeout and no retries. Stop requests prevent subsequent calls and new entries; an in-flight call can complete, after which deterministic paper exits continue. Restarting the server ends active jobs; partial transcripts remain in SQLite observation records.

Approval expires at the next ten-observation review boundary. After the round budget is exhausted, approvals cease and mandatory exits continue. Provider failures or invalid JSON fail closed with no scripted fallback. Token names outside eligible or held sets are rejected. AI vetoes cannot be overridden by the coordinator. The agents receive no future observations or evaluation results. Backtests can still be influenced by model pretraining; synthetic identifiers reduce that concern but do not establish real-data validity.

Set estimated cost per attempted call. OpenAI mode requires a positive estimate; local/demo may use zero. Each full round reserves enough available cash before starting. Attempted calls deduct that estimate from portfolio cash, and net P&L includes it. Responses usage metadata is logged where available. This is **not a provider-enforced dollar cap** or verified bill: actual billing can differ, and a timeout can still be billed. Configure spending limits directly with the provider separately. Baseline is deterministic and incurs no AI cost; it keeps other execution/operation assumptions identical.

The system is a bounded historical replay, not a continuously running live monitor. Fixed risk limits stay external to the model. Developing a new hypothesis or loosening limits requires a separate run. The UI records human-readable decision summaries, not hidden chain-of-thought.

## Validation status

Offline workflow tests use mocked model responses; they verify sequential handoffs, unanimous vetoes, no future evidence, round/cash budgets, cost accounting, cancellation, invalid output handling and OpenAI request shape. Actual OpenAI/Ollama inference has not been run because you chose to select a provider later. Do not interpret a successful scripted demo as successful AI inference or trading edge.
