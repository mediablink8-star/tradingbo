/* tradinglab-price-fix.js — tiny memecoin prices + mark-to-market */
(function () {
  function tokenPrice(v) {
    var x = Number(v);
    if (!Number.isFinite(x) || x <= 0) return "—";
    if (x >= 1) return x.toFixed(4);
    if (x >= 0.01) return x.toFixed(6);
    if (x >= 0.0001) return x.toFixed(8);
    return x.toExponential(4);
  }
  window.tokenPrice = tokenPrice;

  var tries = 0;
  var iv = setInterval(function () {
    tries++;
    if (typeof loadMemeTrader === "function" && !loadMemeTrader.__patched) {
      var orig = loadMemeTrader;
      window.loadMemeTrader = async function () {
        try {
          await fetch("/api/meme/trader/tick", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: "{}",
          });
        } catch (e) {}
        return orig.apply(this, arguments);
      };
      loadMemeTrader.__patched = true;
    }
    if (tries > 40) clearInterval(iv);
  }, 500);

  setInterval(function () {
    if (typeof loadMemeTrader === "function") {
      try { loadMemeTrader(); } catch (e) {}
    }
  }, 15000);
})();
