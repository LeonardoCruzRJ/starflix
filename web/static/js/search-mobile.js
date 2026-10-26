// 54.17: busca do celular — digitou, os resultados aparecem na própria página (até 12 capas, 3 por linha); o mais exato/próximo vem primeiro
(function () {
  var wrap = document.getElementById('m-search');
  if (!wrap) return;
  var inp = document.getElementById('m-sinput'), grid = document.getElementById('m-sgrid'), empty = document.getElementById('m-sempty'), none = document.getElementById('m-snone');
  var PAL = ['#b4d4de', '#ccddf9', '#f6f81a', '#f4b6d2', '#b9f0c4', '#ffcfa3', '#d9bfff', '#9fe3e0'];  // uma cor por biblioteca (estável pelo id)
  var seq = 0, timer = null;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }
  function card(x) {
    var a = el('a', 'ms-card'), p = el('div', 'ms-poster');
    a.href = x.href;
    var im = document.createElement('img');
    im.alt = ''; im.decoding = 'async'; im.src = x.img; im.onerror = function () { im.remove(); };
    p.appendChild(im);
    if (x.age) p.appendChild(el('span', 'ms-age a' + x.age, x.age));
    if (x.last) p.appendChild(el('span', 'ms-last', T('search.last_ep', {last: x.last})));
    a.appendChild(p);
    var t = el('div', 'ms-title', x.title); t.title = x.title; a.appendChild(t);
    var m = el('div', 'ms-meta'), l = el('span', 'ms-lib', x.lib);
    l.style.color = PAL[Math.abs(x.lib_id | 0) % PAL.length];
    m.appendChild(l); m.appendChild(el('i', 'ms-sep'));
    m.appendChild(el('span', 'ms-lang ' + (x.dub ? 'dub' : 'leg'), x.dub ? 'DUB' : 'LEG'));
    m.appendChild(el('span', 'ms-year', x.year ? String(x.year) : ''));
    a.appendChild(m);
    return a;
  }
  function show(items, q) {
    grid.textContent = '';
    if (items.length) {
      items.forEach(function (x) { grid.appendChild(card(x)); });
      grid.hidden = false; empty.hidden = true; none.hidden = true;
    } else {
      grid.hidden = true; empty.hidden = false;
      none.hidden = !q; none.textContent = q ? T('search.none', {q: q}) : '';
    }
  }
  function remember(q) {
    try { history.replaceState(null, '', q ? '/search?q=' + encodeURIComponent(q) : '/search'); } catch (e) {}
  }
  async function run() {
    var q = inp.value.trim(), n = ++seq;
    remember(q);
    if (!q) { show([], ''); return; }
    try {
      var r = await fetch('/search/m?q=' + encodeURIComponent(q), {headers: {Accept: 'application/json'}});
      if (r.status === 401) { location.href = '/login'; return; }
      if (n !== seq || !r.ok) return;  // resposta velha (o usuário já digitou mais): descarta
      var j = await r.json();
      if (n !== seq) return;
      show(j.items || [], q);
    } catch (e) {}
  }
  inp.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(run, 140); });
  wrap.querySelector('form').addEventListener('submit', function (e) { e.preventDefault(); clearTimeout(timer); run(); inp.blur(); });
  if (inp.value.trim()) run();
  else { try { inp.focus(); } catch (e) {} }
})();
