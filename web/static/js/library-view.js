// Modos de exibição da biblioteca (31.10): Grelha · Visualização em Detalhes · Exibição em Tabela (localStorage "sf.view").
// Mantém os mesmos .pcard (seleção, menus, edição): só reorganiza o layout por CSS e injeta os dados extras de /library/<id>/rows.
(function () {
  var bar = document.getElementById('lib-bar'), grid = document.querySelector('.pgrid');
  if (!bar || !grid) { window.sfLibView = {get: function () { return 'grid'; }, set: function () {}}; return; }
  var LIB = bar.dataset.library, DIR = bar.dataset.dir, SORT = bar.dataset.sort;
  var COLS = [['title', 1], ['year', 1], ['rd', 1], ['rt', 1], ['s', 1], ['cc', 1], ['d', 1], ['pr', 0], ['pl', 0], ['ad', 1], ['ex', 0], ['res', 1], ['br', 0]];  // rótulos: lib.col.<k>
  var ICON = {grid: '#i-grid', detail: '#i-view-detail', table: '#i-view-table'};
  var rows = null, head = null, loading = null;

  function mode() { var m = localStorage.getItem('sf.view'); return m === 'detail' || m === 'table' ? m : 'grid'; }
  function cols() {
    try { var c = JSON.parse(localStorage.getItem('sf.cols') || 'null'); if (Array.isArray(c) && c.length) return c; } catch (e) {}
    return ['title', 'year'];
  }
  function dur(s) { return SF_I18N.fmt.hmShort(s); }
  function date(d) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d || ''); return m ? m[3] + '/' + m[2] + '/' + m[1] : ''; }
  function cell(k, card, r) {
    r = r || {};
    if (k === 'year') return (card.querySelector('.pcard-sub') || {}).textContent || '';
    if (k === 'rd') return date(r.rd);
    if (k === 'ad') return date(r.ad);
    if (k === 'rt') return r.rt ? SF_I18N.fmt.dec(Number(r.rt), 1) : '';
    if (k === 's') return r.s ? '★ ' + SF_I18N.fmt.number(r.s / 2, {maximumFractionDigits: 1}) : '';
    if (k === 'cc') return r.cc || '';
    if (k === 'd') return dur(r.d);
    if (k === 'res') return r.res ? r.res + 'p' : '';
    return '';
  }
  function stars(n) {
    var o = '';
    for (var i = 1; i <= 5; i++) o += n >= i * 2 ? '★' : (n === i * 2 - 1 ? '⯪' : '☆');
    return o;
  }
  // pick/edit/more saem do pôster para o card (ficam à esquerda/direita da linha) e voltam ao sair do modo
  function relocate(card, out) {
    var poster = card.querySelector('.pcard-poster'), over = card.querySelector('.pcard-over');
    if (!poster || !over) return;
    var pick = poster.querySelector('.pcard-pick') || card.querySelector(':scope > .pcard-pick');
    var btns = [].slice.call(over.querySelectorAll('.pcard-edit, .pcard-more')).concat([].slice.call(card.querySelectorAll(':scope > .pv-act > button')));
    if (out) {
      if (pick) card.appendChild(pick);
      var act = card.querySelector(':scope > .pv-act');
      if (!act) { act = document.createElement('div'); act.className = 'pv-act'; card.appendChild(act); }
      btns.forEach(function (b) { act.appendChild(b); });
    } else {
      if (pick) poster.insertBefore(pick, over);
      btns.forEach(function (b) { over.appendChild(b); });
      var a = card.querySelector(':scope > .pv-act'); if (a) a.remove();
    }
  }
  function clean(card) {
    [].forEach.call(card.querySelectorAll('.pv, .tv-play'), function (n) { n.remove(); });
  }
  function fill(m) {
    [].forEach.call(grid.querySelectorAll('.pcard[data-pick]'), function (card) {
      clean(card); relocate(card, m !== 'grid');
      if (m === 'grid') return;
      var r = (rows || {})[card.dataset.pick] || {}, pv = document.createElement('div');
      if (m === 'detail') {
        pv.className = 'pv pv-detail';
        var meta = [(card.querySelector('.pcard-sub') || {}).textContent, dur(r.d)].filter(Boolean).join(' · ');
        pv.innerHTML = '<div class="pv-meta"><span></span><span class="pv-stars"></span></div><p class="pv-over"></p>';
        pv.querySelector('.pv-meta span').textContent = meta;
        var st = pv.querySelector('.pv-stars'); st.textContent = stars(r.s || 0); st.classList.toggle('on', !!r.s);
        pv.querySelector('.pv-over').textContent = r.o || '';
        card.insertBefore(pv, card.querySelector('.pv-act'));
      } else {
        pv.className = 'pv pv-cols';
        cols().forEach(function (k) {
          if (k === 'title') return;
          var c = document.createElement('span'); c.className = 'tv-c'; c.textContent = cell(k, card, r); pv.appendChild(c);
        });
        card.insertBefore(pv, card.querySelector('.pv-act'));
        var pl = card.querySelector('.pcard-play');
        if (pl) { var a = document.createElement('a'); a.className = 'tv-play'; a.href = pl.getAttribute('href'); a.setAttribute('aria-label', T('card.play'));
          a.innerHTML = '<svg class="ic ic-sm"><use href="#i-play"/></svg>'; card.insertBefore(a, card.firstChild); }
      }
    });
  }
  function sortBy(k) {
    var q = new URLSearchParams(location.search);
    var cur = SORT === k, d = cur ? (DIR === 'asc' ? 'desc' : 'asc') : (k === 'year' ? 'desc' : 'asc');
    q.set('sort', k); q.set('dir', d); location.search = q.toString();
  }
  function buildHead() {
    if (head) head.remove();
    head = document.createElement('div'); head.className = 'tv-head';
    var pick = document.createElement('button'); pick.type = 'button'; pick.className = 'tv-pick'; pick.setAttribute('aria-label', T('lib.columns'));
    pick.innerHTML = '<svg class="ic"><use href="#i-view-table"/></svg><svg class="ic ic-sm"><use href="#i-chevron-down"/></svg>';
    pick.addEventListener('click', function (e) {
      e.stopPropagation();
      var on = cols();
      window.sfMenuAt(pick, COLS.map(function (c) {
        if (!c[1]) return {l: T('lib.col.' + c[0]), off: 1};
        return {l: T('lib.col.' + c[0]), on: on.indexOf(c[0]) >= 0, fn: function () {
          if (c[0] === 'title') return;
          var n = on.indexOf(c[0]) >= 0 ? on.filter(function (x) { return x !== c[0]; }) : on.concat([c[0]]);
          n = COLS.map(function (x) { return x[0]; }).filter(function (x) { return n.indexOf(x) >= 0 || x === 'title'; });
          localStorage.setItem('sf.cols', JSON.stringify(n)); apply();
        }};
      }), false, 'ctx-lib');
    });
    head.appendChild(pick);
    cols().forEach(function (k) {
      var def = COLS.filter(function (c) { return c[0] === k; })[0]; if (!def) return;
      var h = document.createElement(k === 'title' || k === 'year' ? 'button' : 'span'); h.className = 'tv-h tv-h-' + k; h.textContent = T('lib.col.' + k);
      var key = k === 'year' ? 'year' : k === 'title' ? 'title' : null;
      if (key) {
        h.type = 'button'; h.classList.add('sortable');
        if (SORT === key) { var ar = document.createElement('span'); ar.className = 'tv-arrow'; ar.textContent = DIR === 'asc' ? '↑' : '↓'; h.appendChild(ar); h.classList.add('on'); }
        h.addEventListener('click', function () { sortBy(key); });
      }
      head.appendChild(h);
    });
    var sp = document.createElement('span'); sp.className = 'tv-h tv-h-act'; head.appendChild(sp);
    grid.parentNode.insertBefore(head, grid);
  }
  function apply() {
    var m = mode();
    grid.classList.toggle('pgrid-detail', m === 'detail'); grid.classList.toggle('pgrid-table', m === 'table');
    bar.classList.toggle('v-table', m === 'table');
    var ic = document.querySelector('[data-view-ic]'); if (ic) ic.setAttribute('href', ICON[m]);
    if (head) { head.remove(); head = null; }
    var go = function () { fill(m); if (m === 'table') buildHead(); };
    if (m === 'grid' || rows) { go(); return; }
    if (!loading) loading = fetch('/library/' + LIB + '/rows').then(function (r) { if (r.status === 401) { location.href = '/login'; throw 0; } return r.json(); })
      .then(function (j) { rows = j.rows || {}; }).catch(function () { rows = {}; });
    loading.then(function () { if (mode() === m) go(); });
  }
  window.sfLibView = {get: mode, set: function (m) { localStorage.setItem('sf.view', m); apply(); }};
  if (mode() !== 'grid') apply();
})();
