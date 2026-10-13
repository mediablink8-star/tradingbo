/* Boot: live gate + unified desk */
(function () {
  document.documentElement.classList.add("desk-boot");
  function add(src, attrs) {
    if (document.querySelector('script[src="' + src + '"]')) return;
    var s = document.createElement("script");
    s.src = src + "?v=3";
    if (attrs) Object.keys(attrs).forEach(function (k) { s.setAttribute(k, attrs[k]); });
    (document.body || document.documentElement).appendChild(s);
  }
  function addCss(href) {
    if (document.querySelector('link[href*="' + href + '"]')) return;
    var l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = href + "?v=3";
    document.head.appendChild(l);
  }
  addCss("desk-unify-a.css");
  addCss("desk-unify-b.css");
  add("live-control.js", { "data-live-control": "1" });
  add("desk-unify.js", { "data-desk-unify": "1" });
})();
