/* Boot: live gate + unified desk */
(function () {
  document.documentElement.classList.add("desk-boot");
  function add(src, attrs) {
    if (document.querySelector('script[src="' + src + '"]')) return;
    var s = document.createElement("script");
    s.src = src + "?v=2";
    if (attrs) Object.keys(attrs).forEach(function (k) { s.setAttribute(k, attrs[k]); });
    (document.body || document.documentElement).appendChild(s);
  }
  function addCss(href) {
    var existing = document.querySelector('link[data-desk-unify]');
    if (existing) existing.remove();
    var l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = href + "?v=2";
    l.setAttribute("data-desk-unify", "1");
    document.head.appendChild(l);
  }
  addCss("desk-unify.css");
  add("live-control.js", { "data-live-control": "1" });
  add("desk-unify.js", { "data-desk-unify": "1" });
})();
