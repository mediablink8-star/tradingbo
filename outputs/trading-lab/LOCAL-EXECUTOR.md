# Local executor control foundation

This service is the first Stage 4 milestone. It runs on loopback, stores a
persistent kill switch and audit trail, and accepts signed, time-bounded,
single-use `kill` and `disarm` commands. It has no IBKR adapter, no order
endpoint, no arm endpoint and no path to submit broker orders. Restarting the
process forces the persistent state back to disarmed.

## Run locally

From `outputs/trading-lab`, set a private 32-byte-or-longer random token in
your local shell and start the service:

```powershell
$secretBytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Fill($secretBytes)
$env:TRADINGBO_EXECUTOR_TOKEN = [Convert]::ToBase64String($secretBytes)
$env:TRADINGBO_EXECUTOR_DB = Join-Path $PWD "data/local-executor.sqlite3"
python local_executor_service.py
```

The service binds to `127.0.0.1:8766` by default and rejects non-loopback
addresses. `GET /healthz` returns non-sensitive health; `GET /v1/status` reports
that entries and live order submission are disabled.

## Signed kill/disarm command format

`POST /v1/commands` accepts a JSON object with `command_id` and `action`, where
`action` is `kill` or `disarm`. The caller supplies `X-Command-Timestamp` (Unix
seconds), `X-Command-Nonce` (unique per command), and
`X-Command-Signature` (lowercase HMAC-SHA256 hex). The signature covers
`timestamp + "." + nonce + "." + canonical_json(body)` using sorted keys,
compact separators and UTF-8. Commands outside the 30-second clock window,
with invalid signatures, or with a previously used command ID or nonce are
rejected. The database records command digests and audit events, never the
shared secret.

The service rejects `arm` and every other action. Do not expose this port to a
network or put the shared secret in Render. IBKR contract resolution, a
connected paper account, order reconciliation and a separate reviewed live
adapter are still required before any order capability exists.
