# Pump.fun real-data discovery feed

The dashboard now has **Live Pump.fun discovery**. Start the feed to collect new token creation and migration events. The implementation connects to `wss://pumpportal.fun/api/data` through **PumpPortal, a third-party data provider**, not an official Pump.fun market API.

The provider's documentation lists `subscribeNewToken` and `subscribeMigration` as free. A connection without an API key successfully acknowledged the new-token subscription during verification. The code never subscribes to metered token/account trade streams, never passes an API key, and never accesses trading or wallet endpoints.

Official provider references inspected on 2026-10-06:

- [PumpPortal real-time data](https://pumpportal.fun/data-api/real-time/)
- [PumpPortal third-party disclosure](https://pumpportal.fun/)

## Setup

Python still runs the dashboard. The discovery collector additionally needs **Node.js 22+**, using its built-in WebSocket API without npm packages. The app locates Node on PATH or the bundled Codex runtime on this machine. Start the normal server with `start.ps1`, open http://127.0.0.1:8765 and click **Start real discovery feed**.

One collector connection is shared by all tabs in this server process. Do not run multiple copies of the server/collector. Repeated Start requests are idempotent while the collector runs. Stop terminates the collector and retains saved data. Closing the browser tab does not stop collection; stopping the local server does. The collector does not start automatically after a server restart. The machine and server must stay running to collect observations.

The collector records disconnections and retries after 5, 10, 20, 40, then at most 60 seconds, resetting after a stable connection. Outbound network access is required. This environment's normal execution sandbox blocks outbound sockets; the read-only connectivity probe succeeded outside that sandbox. Connection errors and gaps are explicit, with no synthetic fallback or fabricated events.

## What is recorded

`lab.sqlite` contains `pump_events` with local UTC epoch receive time, provider raw JSON, normalized token mint, event type, symbol/name, market cap in SOL when supplied, and virtual reserves when supplied. `pump_status` records provider control messages, disconnects and other collector lifecycle events. Known signatures/mints/event types are deduplicated. Unknown migration event shapes remain labeled discovery rather than guessing.

The dashboard displays the latest 100 events and links validated mint addresses to Pump.fun. **Export recorded events** exports the latest 1,000 raw/normalized events. The complete collected history stays in SQLite. No retention policy deletes older observations; prolonged operation can grow the database.

Receive timestamps are not chain timestamps, and provider-reported events are not independently RPC-verified. Null fields stay unknown. Market cap in SOL is not a USD price. Virtual bonding-curve reserves are not actual tradable liquidity or executable quotes. Token metadata is untrusted and rendered as text; remote token images and metadata URLs are not fetched automatically.

## Trading boundary

This is discovery data, not a full historical/trade/quote feed. AI paper experiments still use synthetic observations and do not consume these events. A newly launched token also fails the current hypothesis's 24-hour pool-age condition. Connecting live data to research requires further enrichment, token-security evidence, repeated price/volume observations, quote/route checks and prospective evaluation. Real trading remains absent.
