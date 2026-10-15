# App restore notes

`app.py` is a small launcher that reassembles the full application from:

- `_app_b64_0.txt` … `_app_b64_3.txt` (base64 body parts)

On serve, the app injects:

1. **tokenPrice** formatting so memecoin prices are not shown as `$0.00`
2. **POST /api/meme/trader/tick** before status refresh (mark-to-market)
3. **15s** polling instead of 60s

Also present: `tradinglab-price-fix.js` (client-side backup for tick + poll).

## Run

```bash
git pull
cd outputs/trading-lab
python app.py
```

Hard-refresh the browser after restart.
