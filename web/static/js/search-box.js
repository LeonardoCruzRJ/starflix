// Busca instantânea na topbar (23.26): dropdown com pôster, título e ano; Enter vai à página de resultados.
(function () {
  var form = document.querySelector('.topbar .search'), inp = form && form.querySelector('input[name=q]');
  if (!inp) return;
  var box = document.createElement('div'), t = null, seq = 0, idx = -1;
  box.className = 'sbox'; box.hidden = true; form.appendChild(box);
  function hide() { box.hidden = true; idx = -1; }
  function rows() { return box.querySelectorAll('a.sbox-i'); }
  function mark() { Array.prototype.forEach.call(rows(), function (a, i) { a.classList.toggle('on', i === idx); }); }
  async function run() {
    var q = inp.value.trim(), n = ++seq;
    if (!q) { hide(); return; }
    try {
      var r = await fetch('/search?json=1&q=' + encodeURIComponent(q));
      if (n !== seq || !r.ok) return;
      var j = await r.json();
      box.innerHTML = ''; idx = -1;
      if (!j.items.length) { box.innerHTML = '<div class="sbox-e"></div>'; box.firstChild.textContent = T('search.none_short'); box.hidden = false; return; }
      j.items.forEach(function (x) {
        var a = document.createElement('a'); a.className = 'sbox-i'; a.href = x.url;
        var im = document.createElement('img'); im.src = x.img; im.alt = ''; im.onerror = function () { im.style.visibility = 'hidden'; };
        var d = document.createElement('div'), b = document.createElement('b'), s = document.createElement('span');
        b.textContent = x.title; s.textContent = T(x.kind === 'movie' ? 'common.movie' : x.kind === 'video' ? 'search.kind.video' : x.kind === 'collection' ? 'search.kind.collection' : 'common.show') + (x.year ? ' · ' + x.year : '');
        d.appendChild(b); d.appendChild(s); a.appendChild(im); a.appendChild(d); box.appendChild(a);
      });
      box.hidden = false;
    } catch (e) {}
  }
  inp.addEventListener('input', function () { clearTimeout(t); t = setTimeout(run, 180); });
  inp.addEventListener('keydown', function (e) {
    var r = rows();
    if (e.key === 'Escape') { hide(); }
    else if (e.key === 'ArrowDown' && r.length) { e.preventDefault(); idx = (idx + 1) % r.length; mark(); }
    else if (e.key === 'ArrowUp' && r.length) { e.preventDefault(); idx = (idx - 1 + r.length) % r.length; mark(); }
    else if (e.key === 'Enter' && idx >= 0 && r[idx]) { e.preventDefault(); location.href = r[idx].href; }
  });
  inp.addEventListener('focus', function () { if (box.children.length && inp.value.trim()) box.hidden = false; });
  document.addEventListener('click', function (e) { if (!form.contains(e.target)) hide(); });
})();

// V717: ao rolar a página para baixo a busca da topbar some (classe sf-scrolled no <html>); só volta com a página toda no topo.
(function () {
  var root = document.documentElement;
  function upd() { root.classList.toggle('sf-scrolled', (window.pageYOffset || root.scrollTop || 0) > 0); }
  window.addEventListener('scroll', upd, { passive: true });
  window.addEventListener('pageshow', upd);
  upd();
})();
