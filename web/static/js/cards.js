// Cards de pôster (23.3): ○ marca/desmarca assistido (filme/episódio) e recarrega a página.
document.addEventListener('click', async function (e) {
  var b = e.target.closest('.pcard-sel');
  if (!b) return;
  var card = b.closest('.pcard');
  if (!card || !card.dataset.kind || !card.dataset.id) return;
  e.preventDefault();
  b.disabled = true;
  try {
    var r = await fetch('/progress/' + card.dataset.kind + '/' + card.dataset.id + '/watched', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({watched: b.dataset.watched})
    });
    if (r.status === 401) { location.href = '/login'; return; }
    location.reload();
  } catch (err) { b.disabled = false; }
});

// 65.2: marca data-trailer="1" nos cards visíveis de filme/série que têm trailer pronto (um pedido em lote a /trailers/has).
// Cache em sessionStorage por 10 min (inclusive os sem trailer). Nada de vídeo é baixado aqui; a prévia é a 65.3.
(function () {
  if (!('IntersectionObserver' in window) || document.body.dataset.heroTrailer === 'off') return;
  var TTL = 600000, MAX = 100, queue = {}, timer = null, seen = new WeakSet();
  var io = new IntersectionObserver(function (es) {
    es.forEach(function (e) { if (e.isIntersecting) { io.unobserve(e.target); want(e.target); } });
  }, {rootMargin: '200px'});

  function ident(card) {
    var a = card.querySelector('.pcard-link');
    var m = a && /^\/(movie|show)\/(\d+)\/?$/.exec(a.getAttribute('href') || '');
    return m ? {kind: m[1], id: +m[2]} : null;
  }
  function ck(k, i) { return 'sf.tp.' + k + ':' + i; }
  function cached(k, i) {
    try {
      var v = sessionStorage.getItem(ck(k, i));
      if (!v) return null;
      var p = v.split('|');
      return Date.now() - (+p[0]) < TTL ? p[1] : null;
    } catch (e) { return null; }
  }
  function put(k, i, has) { try { sessionStorage.setItem(ck(k, i), Date.now() + '|' + (has ? 1 : 0)); } catch (e) {} }

  function want(card) {
    var it = ident(card);
    if (!it) return;
    var c = cached(it.kind, it.id);
    if (c === '1') { card.dataset.trailer = '1'; return; }
    if (c === '0') return;
    var key = it.kind + ':' + it.id;
    (queue[key] = queue[key] || {it: it, cards: []}).cards.push(card);
    if (!timer) timer = setTimeout(flush, 150);
  }

  async function flush() {
    timer = null;
    var keys = Object.keys(queue).slice(0, MAX), batch = {};
    keys.forEach(function (k) { batch[k] = queue[k]; delete queue[k]; });
    if (Object.keys(queue).length) timer = setTimeout(flush, 150);
    if (!keys.length) return;
    try {
      var r = await fetch('/trailers/has', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({items: keys.map(function (k) { return batch[k].it; })})
      });
      if (!r.ok) return;
      var has = {};
      ((await r.json()).has || []).forEach(function (x) { has[x.kind + ':' + x.id] = 1; });
      keys.forEach(function (k) {
        var yes = !!has[k];
        put(batch[k].it.kind, batch[k].it.id, yes);
        if (yes) batch[k].cards.forEach(function (c) { c.dataset.trailer = '1'; });
      });
    } catch (e) {}
  }

  function scan(root) {
    (root.querySelectorAll ? root.querySelectorAll('.pcard') : []).forEach(function (c) {
      if (!seen.has(c)) { seen.add(c); io.observe(c); }
    });
  }
  function start() {
    scan(document);
    new MutationObserver(function (ms) {
      ms.forEach(function (m) {
        m.addedNodes.forEach(function (n) {
          if (n.nodeType !== 1) return;
          if (n.classList && n.classList.contains('pcard') && !seen.has(n)) { seen.add(n); io.observe(n); }
          else scan(n);
        });
      });
    }).observe(document.body, {childList: true, subtree: true});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();

// 65.3: prévia em balão (16:9) sobre o card com data-trailer: 1 s parado, até 20 s, um vídeo por vez, sem repetir até sair e entrar.
(function () {
  // 65.4: perfil (data-card-preview = auto|on|off; off também quando o admin desliga o trailer), reduced-motion, economia de dados e app (WebView)
  var mode = document.body.getAttribute('data-card-preview') || 'auto';
  if (!window.matchMedia || mode === 'off' || window.StarflixApp || / wv\)/.test(navigator.userAgent)) return;
  try {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    if (navigator.connection && navigator.connection.saveData) return;
    if (!window.matchMedia('(hover: hover)').matches) return;
    if (mode === 'auto' && window.matchMedia('(pointer: coarse)').matches) return;
  } catch (e) { return; }
  var DELAY = 1000, MAXMS = 20000, cur = null, tDelay = null, tMax = null, box = null, vid = null;

  function build() {
    if (box) return;
    box = document.createElement('div'); box.className = 'pcard-pv'; box.setAttribute('aria-hidden', 'true');
    vid = document.createElement('video');
    vid.muted = true; vid.defaultMuted = true; vid.playsInline = true; vid.preload = 'none'; vid.tabIndex = -1;
    vid.addEventListener('playing', function () { if (cur) box.classList.add('on'); });
    vid.addEventListener('ended', function () { stop(true); });
    vid.addEventListener('error', function () { stop(true); });
    box.appendChild(vid); document.body.appendChild(box);
  }
  function place(card) {
    var r = (card.querySelector('.pcard-poster') || card).getBoundingClientRect();
    var w = Math.min(Math.max(r.width * 1.6, 320), window.innerWidth - 16), h = w * 9 / 16;
    box.style.width = w + 'px'; box.style.height = h + 'px';
    box.style.left = Math.max(8, Math.min(r.left + r.width / 2 - w / 2, window.innerWidth - w - 8)) + 'px';
    box.style.top = Math.max(8, Math.min(r.top + r.height / 2 - h / 2, window.innerHeight - h - 8)) + 'px';
  }
  function stop(done) {
    clearTimeout(tDelay); clearTimeout(tMax); tDelay = tMax = null;
    if (box) {
      box.classList.remove('on');
      try { vid.pause(); } catch (e) {}
      vid.removeAttribute('src'); try { vid.load(); } catch (e) {}
    }
    if (cur && done) cur.dataset.pvDone = '1';
  }
  function end() { stop(false); if (cur) delete cur.dataset.pvDone; cur = null; }
  function show(card) {
    var a = card.querySelector('.pcard-link'), m = a && /^\/(movie|show)\/(\d+)\/?$/.exec(a.getAttribute('href') || '');
    if (!m || cur !== card || document.hidden || window.innerWidth < 900 || document.body.classList.contains('sel-on')) return;
    build(); place(card);
    vid.src = '/trailer/' + m[1] + '/' + m[2];
    var p = vid.play(); if (p && p.catch) p.catch(function () { stop(true); });
    tMax = setTimeout(function () { stop(true); }, MAXMS);
  }
  function begin(card) {
    if (cur === card) return;
    end(); cur = card;
    if (card.dataset.pvDone) return;
    tDelay = setTimeout(function () { show(card); }, DELAY);
  }
  function cardOf(el) { return el && el.closest ? el.closest('.pcard[data-trailer="1"]') : null; }

  document.addEventListener('mouseover', function (e) { var c = cardOf(e.target); if (c) begin(c); });
  document.addEventListener('mouseout', function (e) { if (cur && !(e.relatedTarget && cur.contains(e.relatedTarget))) end(); });
  document.addEventListener('focusin', function (e) { var c = cardOf(e.target); if (c && e.target.matches && e.target.matches(':focus-visible')) begin(c); });
  document.addEventListener('focusout', function (e) { if (cur && !(e.relatedTarget && cur.contains(e.relatedTarget))) end(); });
  window.addEventListener('scroll', function () { if (cur) end(); }, true);
  window.addEventListener('resize', function () { if (cur) end(); });
  document.addEventListener('click', function () { if (cur) end(); }, true);
  document.addEventListener('contextmenu', function () { if (cur) end(); }, true);
  document.addEventListener('keydown', function (e) { if (cur && e.key === 'Escape') end(); }, true);
  document.addEventListener('visibilitychange', function () { if (document.hidden && cur) end(); });
})();
