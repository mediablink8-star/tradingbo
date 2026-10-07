# Real-swap pilot

The dashboard now includes Jupiter setup, mainnet buy/sell preparation, on-chain simulation, explicit Phantom approval, and transaction confirmation. It is a wallet-approved pilot, not autonomous AI execution. No real swap has been submitted or tested with a funded wallet.

Connect Phantom and an OpenAI key for the paper team. Separately, connect a Jupiter API key using the real-swap panel. Jupiter keys are held only in process memory or supplied through JUPITER_API_KEY. They are not returned by setup state or written to the database. A prepared transaction is public transaction data, not a private key.

Preparation checks the exact mint address and legacy token ownership. Buys reject active or unknown mint/freeze authorities; Token-2022 is unsupported. Quotes require exact input, fixed 50 bps slippage, a bounded quoted impact, and a reverse route for buys. A reverse quote is not a guarantee that a later sell will be available. Prepare uses a live SOL/USDC route to convert the requested allocation; USDC-equivalent is an estimate, not a guaranteed dollar value.

Transactions must be unsigned legacy messages requiring only the connected wallet signer, contain Jupiter, and use permitted top-level programs. Approve / revoke / set-authority SPL instructions are rejected. This validation is not a full audit of Jupiter CPI routes. Provider construction and wallet review remain trust boundaries. Unsupported transactions fail closed.

The app simulates without broadcasting, checks simulated wallet SOL debit and the minimum requested output delivered to the wallet, requires a 0.01 SOL balance allowance above the input, and verifies a bounded network fee. Simulation does not establish holder concentration, LP ownership, market profitability, or future exit liquidity.

Each buy is at most 10 USDC-equivalent before costs. A persistent per-wallet 100 USDC-equivalent reservation cap includes prepared attempts, conservative estimated rent/fees and sell costs. Reservations are never automatically recycled, even for rejected, expired or failed attempts. This may exhaust the pilot budget without consuming the same amount on-chain. It is an application reservation limit, not an on-chain spending policy or guarantee of maximum wallet loss. Sells remain available when purchases are stopped or the reservation cap is reached.

The review expires after 45 seconds and block-height validation. Changing wallet or form clears the reviewed proposal. Sending first consumes a once-only handoff in the database, then opens Phantom using its documented signAndSendTransaction request. The server does not sign or broadcast. Wallet rejection or uncertain delivery is never automatically retried. If a wallet submission becomes uncertain, inspect Phantom and the explorer before making another attempt. The app cannot recover an unreturned signature automatically.

Confirmation reads the mainnet transaction and compares its message hash with the prepared transaction. Pending or missing chain records are never reported as confirmed. Confirmed transaction errors are recorded as failed. Saved records survive server restart. The emergency buy stop is latched; it prevents new buy handoffs, but cannot cancel an already handed-off or broadcast transaction. Sells remain available. There is no real-money automatic stop-loss or autonomous liquidation worker in this pilot.

Use run-with-recovery.ps1 instead of start.ps1 for local process recovery when the current dashboard copy is stopped. It restarts an exited server. This is not hosting, a Windows service, or a guarantee of 24/7 uptime. Restarting loses session API keys, causing new provider activity to wait for configuration. Sleeping or offline machines cannot trade.

Verification: 55 Python tests pass; wallet UI mocks and dashboard syntax checks pass. Checks include unsafe mint authorities, quote mismatch, invalid signer/program envelopes, simulation/fee failures, persistent budget, once-only handoff, stale proposals, buy-stop versus sell behavior, and message-matched confirmations. No paid model call, real user wallet approval or transaction broadcast was performed.

Official API references:
- https://developers.jup.ag/docs/api-reference/swap/v1/quote
- https://developers.jup.ag/docs/api-reference/swap/v1/swap
- https://docs.phantom.com/solana/sending-a-transaction
- https://solana.com/docs/rpc/http/simulatetransaction
- https://solana.com/docs/rpc/http/gettransaction

RPC compatibility: buy simulations must provide preTokenBalances and postTokenBalances including owner and mint. If the RPC node omits these fields, buys fail closed; the pilot has not been exercised against a funded real wallet.
