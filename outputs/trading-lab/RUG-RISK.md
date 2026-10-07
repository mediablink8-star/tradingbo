# Basic rug-risk screening

The Token risk screen panel reads exact-mint evidence from Solana confirmed RPC and DEX Screener. It returns basic_checks_passed, rejected or unknown, with explicit reasons and warnings. These starter thresholds are engineering choices, not universal financial safety thresholds.

Buy gates:
- Legacy SPL mint initialized; mint and freeze authority explicitly absent. Unsupported programs/extensions or unknown authorities are rejected.
- Usable pool data: price positive, liquidity at least $100,000, pool age at least 24 hours. No inferred missing values.
- Get the 20 largest token accounts, fetch their parsed owner/mint/balance, and aggregate repeated owners. Reject a sampled owner over 20% of total supply, or the top ten sampled owners over 50%. Account amount/decimals/mint mismatches, duplicate accounts, zero supply, absent evidence and inconsistent supply totals reject the screen.
- Include pool/vault accounts conservatively; no unverified automatic pool exemption. This may reject legitimate markets. The result is a sampled supply concentration measure, not a complete holder or insider analysis.
- Reject an observed 30% liquidity drop versus the previous same-pool observation within 24 hours. First observations and changed pools cannot establish this trend and carry warnings. Liquidity history is captured only when the token is scanned; it is not continuous monitoring of every pool.
- Required evidence expires 90 seconds after collection begins. Providers may rate-limit or omit data; unknown blocks entry.

Real buys run a fresh risk scan before quoting/building and must use a single route through the exact screened pool. Reports are included in the prepared swap, must remain fresh through wallet handoff, and survive restart in the audit log. Existing quote, reverse-route and simulation checks still apply. The new risk gate does not block sells.

Live AI paper reviews check at most one candidate per review to limit RPC work, preferring the least recently checked candidate. No real model call is made when screening rejects or returns unknown. Reports and the knowledge rules are supplied to the AI; strategy pending fills require fresh allowed screening. Existing positions still follow exit rules. The momentum-only comparison baseline remains separate and does not pretend to have undergone on-chain risk screening. Synthetic workflow demonstrations retain synthetic fixtures and cannot establish real token safety.

AI knowledge: token metadata/socials are untrusted; exact mint matters; no authority or liquidity claims may be invented; a sell quote is not proof of future selling; failed screening must not prevent exits; hard gates cannot be overridden. LP lock/burn status, creator history, hidden related wallets, developer sales and holder ownership outside the 20-account sample are explicitly unverified. No score or pass certifies a token as safe or rug-proof.

Audit: token_risk SQLite table stores each report with token, timestamps, metrics, thresholds, reasons and warnings. Public risk inspection needs no model or Jupiter API key. It does not request wallet signatures or broadcast transactions.

Verification: 68 Python tests passed. Tests cover same-owner account aggregation, supply/account consistency, unknown authorities, pool age/liquidity, observed liquidity drops, changed pools, stale data, provider failures, direct-pool route matching, buy rejection and unaffected exit behavior. No funded trade or paid AI run was performed.

Sources:
- https://solana.com/docs/rpc/http/gettokenlargestaccounts
- https://solana.com/docs/rpc/http/gettokensupply
- https://solana.com/docs/rpc/http/getmultipleaccounts
- https://docs.dexscreener.com/api/reference

Live check: the public reference-mint scan returned unknown / required_evidence_unavailable. The endpoint preserved allowed=false and certified_safe=false; no token was declared safe and no transaction was sent. This scanner depends on public RPC availability and can block legitimate tokens when provider data is unavailable. Liquidity comparison retains the last usable pool observation across failed scans.
