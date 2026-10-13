/* Ensures LIVE RISK GATE panel loads even if agent-deck cache is stale */
(function () {
  if (document.querySelector('script[data-live-control]')) return;
  var s = document.createElement('script');
  s.src = 'live-control.js';
  s.dataset.liveControl = '1';
  (document.body || document.documentElement).appendChild(s);
})();
