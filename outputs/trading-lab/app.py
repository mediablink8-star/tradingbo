"""Ember Forex Trading Lab HTTP application — launcher."""
import argparse
import base64
import os
import threading
import zlib
from pathlib import Path

_root = Path(__file__).resolve().parent


def _load() -> str:
    # Primary: zlib body across zb_0..5 (small chunks survive git push)
    zparts = []
    for i in range(6):
        p = _root / f"zb_{i}.txt"
        if not p.exists() or p.stat().st_size < 10:
            zparts = []
            break
        zparts.append(p.read_text(encoding="ascii").strip())
    if len(zparts) == 6:
        return zlib.decompress(base64.b64decode("".join(zparts))).decode("utf-8")

    # Secondary: zbody_0..2
    zparts = []
    for name in ("zbody_0.txt", "zbody_1.txt", "zbody_2.txt"):
        p = _root / name
        if not p.exists() or p.stat().st_size < 10:
            zparts = []
            break
        zparts.append(p.read_text(encoding="ascii").strip())
    if len(zparts) == 3:
        return zlib.decompress(base64.b64decode("".join(zparts))).decode("utf-8")

    # Legacy base64 halves
    parts = []
    for name in ("_app_b64_0.txt", "_app_b64_1.txt", "_app_b64_2.txt", "_app_b64_3.txt"):
        text = (_root / name).read_text(encoding="ascii").strip()
        if not text:
            raise RuntimeError(f"empty app body part: {name}")
        parts.append(text)
    p1 = base64.b64decode(parts[0] + parts[1])
    p2 = base64.b64decode(parts[2] + parts[3])
    return (p1 + p2).decode("utf-8")


_src = _load()

# Add a client-side Phantom connect button to the embedded dashboard as well as
# the readable index.html source. This only requests wallet connection/public key;
# it never asks the wallet to sign or submit a transaction.
_phantom_button_old = '<button type="button" class="btn" id="themeToggle" title="Cycle visual theme: terminal → 2029 neon → unified desk" style="font:600 9.5px/1 var(--mono);letter-spacing:.1em;padding:5px 10px;border-radius:5px;margin-left:8px">2029</button>'
_phantom_button_new = _phantom_button_old + '\n      <button type="button" class="btn go" id="phantomConnect" aria-label="Connect Phantom wallet" title="Connect your Phantom wallet; no transactions will be signed" style="font:600 9.5px/1 var(--mono);letter-spacing:.06em;padding:7px 10px;margin-left:6px;white-space:nowrap">CONNECT PHANTOM</button>'
if _phantom_button_old in _src:
    _src = _src.replace(_phantom_button_old, _phantom_button_new, 1)

_phantom_runtime_js = r"""
(function initPhantomWallet(){
  const btn=document.getElementById('phantomConnect');
  if(!btn)return;
  let provider=null,connectedAddress='';
  const shortAddress=a=>a.length>12?a.slice(0,5)+'…'+a.slice(-5):a;
  const setConnected=a=>{
    connectedAddress=a||'';
    btn.textContent=connectedAddress?shortAddress(connectedAddress):'CONNECT PHANTOM';
    btn.title=connectedAddress?'Connected wallet: '+connectedAddress+' (click to disconnect)':'Connect your Phantom wallet; no transactions will be signed';
    btn.setAttribute('aria-label',connectedAddress?'Disconnect Phantom wallet '+connectedAddress:'Connect Phantom wallet');
    btn.classList.toggle('go',!connectedAddress);
    btn.classList.toggle('wallet-connected',!!connectedAddress);
  };
  const findProvider=()=>{
    if(window.phantom&&window.phantom.solana&&window.phantom.solana.isPhantom)return window.phantom.solana;
    if(window.solana&&window.solana.isPhantom)return window.solana;
    return null;
  };
  provider=findProvider();
  if(provider&&provider.publicKey)setConnected(String(provider.publicKey));
  if(provider&&provider.on){
    provider.on('connect',key=>setConnected(String(key||provider.publicKey||'')));
    provider.on('disconnect',()=>setConnected(''));
    provider.on('accountChanged',key=>setConnected(key?String(key):''));
  }
  btn.addEventListener('click',async()=>{
    btn.disabled=true;
    try{
      provider=findProvider();
      if(connectedAddress&&provider){await provider.disconnect();setConnected('');return;}
      if(!provider){
        btn.textContent='PHANTOM NOT FOUND';
        btn.title='Install Phantom from https://phantom.app/ then reload Tradingbo';
        if(window.confirm('Phantom was not detected. Open the official Phantom website to install it?'))window.open('https://phantom.app/','_blank','noopener,noreferrer');
        return;
      }
      const result=await provider.connect();
      const address=String((result&&result.publicKey)||provider.publicKey||'');
      if(!address)throw new Error('Phantom did not return a public wallet address.');
      setConnected(address);
    }catch(error){
      btn.title=error&&error.code===4001?'Connection request was rejected in Phantom.':((error&&error.message)||'Unable to connect to Phantom.');
      btn.textContent='CONNECT PHANTOM';
    }finally{btn.disabled=false;}
  });
})();
"""
_phantom_script_marker = "setInterval(tickClock,1000);"
if _phantom_script_marker in _src and "function initPhantomWallet()" not in _src:
    _src = _src.replace(_phantom_script_marker, _phantom_runtime_js + "\n" + _phantom_script_marker, 1)
_phantom_css_marker = ".btn:disabled{opacity:.55;cursor:not-allowed}"
if _phantom_css_marker in _src and "#phantomConnect.wallet-connected" not in _src:
    _src = _src.replace(_phantom_css_marker, _phantom_css_marker + "\n#phantomConnect.wallet-connected{background:rgba(47,191,135,.12);border-color:#2fbf87;color:#7ee2b7}\n#phantomConnect{max-width:175px;overflow:hidden;text-overflow:ellipsis}", 1)
_src = _src.replace(
    '"    renderMemeTrader(await api(\'/api/meme/trader\'));",\n                        1,',
    '"    renderMemeTrader(await api(\'/api/meme/trader\'));}",\n                        1,',
    1,
)
_src = _src.replace(
    "renderMemeTrader(await api('/api/meme/trader'));\n  catch(e)",
    "renderMemeTrader(await api('/api/meme/trader'));}\n  catch(e)",
)

# The dashboard loads its read-only data through fetch(). Basic Auth
# challenges on GET fetches are unreliable in embedded/mobile browsers.
# Keep only explicitly read-only paper/demo endpoints public.
_auth_guard_old = (
    "        # Let the static dashboard load so it can present an in-page login.\n"
    "        # All API data and state-changing requests remain authenticated.\n"
    "        if path.startswith(\"/api/\") and not self._require_auth():"
)
_auth_guard_new = (
    "        # Only read-only paper/demo status is public; mutations and config stay protected.\n"
    "        public_dashboard_gets = {\n"
    "            \"/api/forex\", \"/api/forex/agents\", \"/api/forex/bars\",\n"
    "            \"/api/meme/research\", \"/api/meme/paper\", \"/api/meme/trader\",\n"
    "        }\n"
    "        if path.startswith(\"/api/\") and path not in public_dashboard_gets and not self._require_auth():"
)
if _auth_guard_old in _src:
    _src = _src.replace(_auth_guard_old, _auth_guard_new, 1)
elif "public_dashboard_gets" not in _src:
    raise RuntimeError("Could not apply read-only dashboard auth fix: source guard not found.")

# Strip the `if __name__ == "__main__"` block so we can install route
# extensions before starting the server.
_main_marker = "\nif __name__ == \"__main__\""
_cut = _src.rfind(_main_marker)
if _cut >= 0:
    _src = _src[:_cut]

exec(compile(_src, str(_root / "app.py"), "exec"), globals())

try:
    import live_routes

    if "Handler" in globals():
        live_routes.install(Handler, globals())
        print("Live risk gate installed (/api/live/*).", flush=True)
except Exception as _live_exc:
    print(f"Live risk gate not installed: {_live_exc}", flush=True)

# Jupiter memecoin routes are installed for status/quote diagnostics only.
# Never load a server-side wallet secret, even if it remains configured manually
# in the hosting dashboard. The server-side key/sign/broadcast endpoints are blocked.
os.environ.pop("SOLANA_PRIVATE_KEY", None)
try:
    import jupiter_bot
    if "Handler" in globals():
        jupiter_bot.install(Handler, globals())
        _jupiter_do_post = Handler.do_POST

        def _paper_only_jupiter_post(self):
            import urllib.parse
            path = urllib.parse.urlsplit(self.path).path
            if path in ("/api/jupiter/connect", "/api/jupiter/swap"):
                if hasattr(self, "_require_auth") and not self._require_auth():
                    return
                self.send_json({
                    "ok": False,
                    "error": "Server-side wallet keys and live Solana execution are disabled in this deployment.",
                }, 403)
                return
            return _jupiter_do_post(self)

        Handler.do_POST = _paper_only_jupiter_post
        print("Jupiter status/quote routes installed; server-side connect/swap disabled.", flush=True)
except Exception as _jup_exc:
    print(f"Jupiter trading routes not installed: {_jup_exc}", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ember Forex Trading Lab")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    args = parser.parse_args()

    if AUTH_REQUIRED and (not AUTH_USERNAME or not AUTH_PASSWORD):
        raise SystemExit("Hosted mode requires TRADINGLAB_USERNAME and TRADINGLAB_PASSWORD.")
    if AUTH_REQUIRED and len(AUTH_PASSWORD) < 16:
        raise SystemExit("TRADINGLAB_PASSWORD must be at least 16 characters.")

    if AGENTS.auto_run:
        def _agent_loop():
            while True:
                try:
                    AGENTS.agent_cycle()
                except Exception as exc:
                    print(f"[agent_loop] {exc}", flush=True)
                time.sleep(int(os.environ.get("AGENT_CYCLE_INTERVAL", "300")))

        threading.Thread(target=_agent_loop, daemon=True).start()
        print("Forex paper-agent auto-run enabled.", flush=True)
    else:
        print("Forex paper-agent auto-run disabled; use Run agent cycle in dashboard.", flush=True)

    if os.environ.get("MEME_PAPER_AUTORUN", "").strip() == "1":
        def _meme_loop():
            while True:
                try:
                    run_meme_trader()
                except Exception as exc:
                    print(f"[meme_loop] {exc}", flush=True)
                time.sleep(int(os.environ.get("MEME_CYCLE_INTERVAL", "120")))

        threading.Thread(target=_meme_loop, daemon=True).start()
        print("Solana meme paper-trading auto-run enabled.", flush=True)
    else:
        print("Solana meme paper-trading auto-run disabled; use Run paper cycle in dashboard.", flush=True)

    print(f"Ember Forex Trading Lab listening on {args.host}:{args.port}", flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
