# Ember Capital

Ember Capital is an AI-agent trading company prototype: a research and paper-
trading dashboard with persistent company operations, multi-role agent reviews,
performance tracking and a wallet-approved Solana swap pilot. The agent company
currently makes paper decisions; it is not connected to live execution.

## Run locally

Requires Python 3.10 or later and the packages listed in
`outputs/trading-lab/requirements.txt`.

```powershell
cd outputs/trading-lab
python -m pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:8765`. The company office is at
`http://127.0.0.1:8765/company.html`. Alternatively, run
`outputs/trading-lab/start.ps1` from PowerShell.

## Product status

- Agent research, company work orders, the paper portfolios, audit journal and
  persistent operations dashboard are implemented.
- Model-provider access, market-data availability and hosted credentials need
  owner setup; successful provider connectivity is not implied by the UI.
- The browser-approved Jupiter pilot is separate from AI decisions and requires
  explicit Phantom approval for each transaction.
- A legacy server-side Jupiter auto-trading worker also exists in the code. It
  can submit real swaps when explicitly enabled with `JUPITER_AUTORUN=1`, but it
  is not connected to AI proposals or the persistent live risk gate. The checked-
  in Render configuration keeps it disabled (`JUPITER_AUTORUN=0`).
- Profitability, a funded wallet, a signing-service policy, and 24/7 operation
  have not been established.

See [the product and setup guide](outputs/trading-lab/README.md) and
[live execution status](outputs/trading-lab/LIVE-AUTONOMY.md) before deploying
or configuring any wallet. Local account databases, credentials, working files
and generated previews are excluded from Git.
