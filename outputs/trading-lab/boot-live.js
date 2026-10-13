/* Boot: live gate + unified desk */
(function () {
  function add(src, attrs) {
    if (document.querySelector('script[src="' + src + '"]')) return;
    var s = document.createElement("script");
    s.src = src;
    if (attrs) Object.keys(attrs).forEach(function (k) { s.setAttribute(k, attrs[k]); });
    (document.body || document.documentElement).appendChild(s);
  }
  function addCss(href) {
    if (document.querySelector('link[href="' + href + '"]')) return;
    var l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = href;
    document.head.appendChild(l);
  }
  addCss("desk-unify.css");
  add("live-control.js", { "data-live-control": "1" });
  add("desk-unify.js", { "data-desk-unify": "1" });
})();
