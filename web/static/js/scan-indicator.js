// 35.8: ícone do Painel com círculo girando e capas em exame com etiqueta girando (só admin, só durante o exame).
(function () {
  var NS = 'http://www.w3.org/2000/svg';
  function ring() {
    var s = document.createElementNS(NS, 'svg'), c = document.createElementNS(NS, 'circle');
    s.setAttribute('viewBox', '0 0 44 44'); s.setAttribute('class', 'scan-arc'); s.setAttribute('aria-hidden', 'true');
    c.setAttribute('cx', '22'); c.setAttribute('cy', '22'); c.setAttribute('r', '19'); s.appendChild(c);
    return s;
  }
  var link = document.querySelector('a.icon-btn[href="/admin"]'), top = null, ids = {}, scanning = false, busy = false, seq = null;
  if (link) { top = document.createElement('span'); top.className = 'scan-top'; top.hidden = true; top.appendChild(ring()); link.appendChild(top); }

  function badge() {
    var b = document.createElement('span'); b.className = 'scan-badge'; b.setAttribute('title', 'Examinando…');
    b.appendChild(ring());
    var s = document.createElementNS(NS, 'svg'), u = document.createElementNS(NS, 'use');
    s.setAttribute('class', 'ic scan-tag'); u.setAttribute('href', '#i-tag'); s.appendChild(u); b.appendChild(s);
    return b;
  }

  function apply() {
    if (busy) return; busy = true;
    if (top) top.hidden = !scanning;
    var pg = pageId(), pbox = document.querySelector('.mv-poster');
    if (pbox) {
      var phas = pbox.querySelector('.scan-badge'), pon = scanning && pg && ids[pg];
      if (pon && !phas) pbox.appendChild(badge()); else if (!pon && phas) phas.remove();
    }
    document.querySelectorAll('.pcard').forEach(function (card) {
      var a = card.querySelector('.pcard-title'), m = a && a.getAttribute('href') && a.getAttribute('href').match(/^\/(?:movie|show)\/(\d+)$/);
      var on = scanning && m && ids[m[1]], has = card.querySelector('.scan-badge'), box = card.querySelector('.pcard-poster');
      if (on && !has && box) { card.classList.add('pcard-scan'); box.appendChild(badge()); }
      else if (!on && has) { card.classList.remove('pcard-scan'); has.remove(); }
    });
    busy = false;
  }

  function pageId() { var m = location.pathname.match(/^\/(?:movie|show)\/(\d+)$/); return m ? m[1] : null; }
  function cardId(card) {
    var a = card.querySelector('.pcard-title'), m = a && a.getAttribute('href') && a.getAttribute('href').match(/^\/(?:movie|show)\/(\d+)$/);
    return m ? m[1] : null;
  }
  // 35.9: capa nova aparece na hora, sem Ctrl+Shift+R (carrega em segundo plano e troca)
  // 35.15: título e ano do card também mudam assim que o item termina
  async function refreshTexts(list) {
    try {
      var r = await fetch('/admin/scan-cards?ids=' + list.join(','), {headers: {Accept: 'application/json'}});
      if (!r.ok) return;
      var items = (await r.json()).items || {};
      document.querySelectorAll('.pcard').forEach(function (card) {
        var id = cardId(card), d = id && items[id]; if (!d) return;
        var t = card.querySelector('.pcard-title'), ph = card.querySelector('.pcard-ph'), sub = card.querySelector('.pcard-sub');
        if (t && d.title && t.textContent !== d.title) { t.textContent = d.title; t.setAttribute('title', d.title); if (ph) ph.textContent = d.title; }
        var y = d.year ? String(d.year) : '';
        if (sub && sub.textContent !== y) { if (y) sub.textContent = y; else sub.remove(); }
        else if (!sub && y && t) { sub = document.createElement('div'); sub.className = 'pcard-sub'; sub.textContent = y; t.insertAdjacentElement('afterend', sub); }
      });
    } catch (e) {}
  }
  // 35.18: reordena/atualiza a grade conforme o filtro e a ordenação vigentes (busca a própria página e move os cards)
  var sorting = false;
  function gridKey(card) {
    if (card.dataset.collection) return 'c' + card.dataset.collection;
    var id = cardId(card); return id ? 'm' + id : null;
  }
  async function resortGrid() {
    var grid = document.querySelector('.pgrid'), bar = document.getElementById('lib-bar');
    if (!grid || !bar || sorting) return;
    sorting = true;
    try {
      var r = await fetch(location.href, {headers: {Accept: 'text/html'}}); if (!r.ok) return;
      var doc = new DOMParser().parseFromString(await r.text(), 'text/html');
      var ng = doc.querySelector('.pgrid'); if (!ng) return;
      var old = {}; grid.querySelectorAll(':scope > .pcard').forEach(function (c) { var k = gridKey(c); if (k) old[k] = c; });
      var frag = document.createDocumentFragment(), seen = {};
      ng.querySelectorAll(':scope > .pcard').forEach(function (c) {
        var k = gridKey(c); if (!k) return; seen[k] = 1;
        frag.appendChild(old[k] || document.importNode(c, true));
      });
      Object.keys(old).forEach(function (k) { if (!seen[k]) old[k].remove(); });
      grid.appendChild(frag);
      var cnt = doc.querySelector('.lib-count'), cur = document.querySelector('.lib-count');
      if (cnt && cur) cur.textContent = cnt.textContent;
      var g1 = doc.querySelector('[data-dd="genre"]'), g2 = document.querySelector('[data-dd="genre"]');
      if (g1 && g2 && g1.dataset.genres) g2.dataset.genres = g1.dataset.genres;
      apply();
    } catch (e) {} finally { sorting = false; }
  }
  var kicked = {}, wasScanning = false;
  function refreshCovers(list) {
    var pg = pageId();
    if (pg && list.indexOf(Number(pg)) !== -1) { location.reload(); return; }  // página do item: mostra capa e dados novos
    refreshTexts(list);
    if (list.some(function (i) { return kicked[i]; })) { list.forEach(function (i) { delete kicked[i]; }); setTimeout(resortGrid, 250); }
    var want = {}; list.forEach(function (i) { want[i] = 1; });
    document.querySelectorAll('.pcard').forEach(function (card) {
      var id = cardId(card); if (!id || !want[id]) return;
      var link = card.querySelector('.pcard-link'); if (!link) return;
      var src = '/poster/' + id + '?t=' + Date.now(), pre = new Image();
      pre.onload = function () {
        var img = link.querySelector('img');
        if (!img) { img = document.createElement('img'); img.alt = ''; img.onerror = function () { this.remove(); }; link.appendChild(img); }
        img.src = src;
      };
      pre.src = src;
    });
  }

  var timer = null;
  async function tick() {
    var wait = 6000;
    try {
      var r = await fetch('/admin/scan-state' + (seq === null ? '' : '?since=' + seq), {headers: {Accept: 'application/json'}});
      if (r.ok) {
        var j = await r.json(); scanning = !!j.scanning; ids = {};
        (j.ids || []).forEach(function (i) { ids[i] = 1; });
        seq = j.seq; if (j.done && j.done.length) refreshCovers(j.done);
        if (wasScanning && !j.scanning) setTimeout(resortGrid, 250);
        wasScanning = !!j.scanning;
        wait = scanning ? 1500 : 6000; apply();
      }
    } catch (e) {}
    timer = setTimeout(tick, wait);
  }
  // 35.16: chamado ao corrigir uma correspondência — o ícone gira já, sem esperar o próximo ciclo
  window.sfScanKick = function (id) { kicked[id] = 1; ids[id] = 1; scanning = true; apply(); clearTimeout(timer); timer = setTimeout(tick, 400); };
  var root = document.querySelector('.content');
  if (root && window.MutationObserver) {
    var t = null;
    new MutationObserver(function () { if (!scanning && !root.querySelector('.scan-badge')) return; clearTimeout(t); t = setTimeout(apply, 80); })
      .observe(root, {childList: true, subtree: true});
  }
  tick();
})();
