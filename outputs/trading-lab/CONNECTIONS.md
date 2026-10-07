# Model and Solana wallet setup

Open http://127.0.0.1:8765/ and use the connection panel at the top.

1. Enter your OpenAI API key and exact model ID. Click Connect model key. The input clears immediately after submission. The entered key stays only in the local server process, not in files, SQLite, logs, exports or browser storage. Restarting the server forgets it. An existing OPENAI_API_KEY environment setting remains a fallback.
2. Click Check connection to list account-accessible models without an inference request. Listing a model does not prove compatibility with this app's strict structured output; model errors fail closed during paper runs. The check does not start the agent team.
3. Set the estimated model cost and daily call allowance in the paper trial. Pause any running observer, wait until stopped, then start the trial with OpenAI selected. No extra paper capital is added.
4. Use Connect Phantom in a browser with the Phantom extension installed and approve sharing the public address. The Codex in-app browser may not expose wallet extensions; use Chrome or Edge if the button reports Phantom unavailable.
5. The balance button reads finalized mainnet SOL only. Account changes and disconnections clear old balances. A manually entered public address is explicitly watch-only and does not establish ownership.

Wallet funds stay in the wallet. This feature does not grant spending permission, provide a deposit account, create a real trading balance, request a signature, or run real trades. No seed phrase or private key is collected. Model keys are for OpenAI only; local Ollama remains available separately. No user API key or real wallet has been tested by the developer.

Local credential endpoints require the dashboard's browser origin. All endpoints reject unexpected Host headers; responses containing setup state use no-store caching. A request already sent to the model provider may finish after forgetting the entered key. The server must remain local to this machine.

Sources: https://developers.openai.com/api/reference/resources/models/methods/list ; https://docs.phantom.com/solana/establishing-a-connection ; https://solana.com/docs/rpc/http/getbalance

Verification: 43 Python tests passed and mocked connection UI checks passed, plus JavaScript syntax checks. Tests cover secret exclusion, session credentials in model requests, GET-only model verification, public address validation, lamport conversion, RPC failures, local origin / Host checks, wallet account changes and disconnection. Real Phantom popup approval requires the user's wallet-equipped browser.
Live verification: dashboard returned HTTP 200, connection panel was present, and the mainnet balance endpoint successfully returned a finalized SOL balance for a public reference account. No user wallet was connected.
