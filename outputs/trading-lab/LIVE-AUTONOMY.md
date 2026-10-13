# Live autonomy — phase 1 (risk gate)

## Your agreed parameters ($100 first wallet)

| Limit | Value | Why |
|-------|-------|-----|
| Wallet ceiling | **$100** | Total you said you can lose |
| Max per trade | **$12** | ~12% of book; leaves room for fees/slippage |
| Max loss / day | **$25** | Stops a single bad day from wiping the wallet |
| Max open positions | **2** | Avoid stacking correlated meme risk |
| Max exposure | **$30** | Cash + open notional bound |
| ARM TTL | **24 hours** | You must re-ARM daily from the phone |
| Default state | **DISARMED** | No new live orders until you ARM |

Agents **cannot** ARM the bot or raise these limits.

## Phone controls

1. Open the deployed app and log in.
2. Find **LIVE RISK GATE** (top of Command Deck / trader area).
3. Tap **ARM** to allow gated live orders for up to 24h.
4. Tap **DISARM** anytime — freezes **new** orders immediately.

## What is not enabled yet

On-chain signing / Jupiter swaps are **not** turned on in this phase.
This deploy adds the **control plane** (ARM/DISARM + hard gates + audit log).
Next phase wires execution only when ARM is on and `can_open()` passes.

## Render env (already required)

- `TRADINGLAB_AUTH_REQUIRED=1`
- `TRADINGLAB_USERNAME` / `TRADINGLAB_PASSWORD` (password ≥ 16 chars)
