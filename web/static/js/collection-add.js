// Modal "Adicionar à Coleção" (24.5): window.sfAddToCollection(ids, kind) — usado pela barra de seleção (bulk-bar.js).
(function () {
  var el = document.createElement('div'); el.className = 'em-overlay'; el.hidden = true;
  el.innerHTML = '<div class="em-win em-small ca-win"><div class="em-head"><span></span><button type="button" class="em-x" aria-label="">✕</button></div>' +
    '<div class="em-pane"><input type="text" class="em-q" placeholder="" autocomplete="off"><div class="ca-list"></div></div>' +
    '<div class="em-foot ca-foot"><input type="text" class="em-q ca-name" maxlength="100" aria-label=""><button type="button" class="em-btn em-save"></button></div></div>';
  document.body.appendChild(el);
  var Q = el.querySelector('.em-q'), L = el.querySelector('.ca-list'), N = el.querySelector('.ca-name'), OK = el.querySelector('.em-save');
  var cols = [], ids = [], lib = null, busy = false;

  function close() { el.hidden = true; }
  function fold(s) { return (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase(); }
  function say(msg) { L.innerHTML = ''; var d = document.createElement('div'); d.className = 'ca-empty'; d.textContent = msg; L.appendChild(d); }
  async function call(url, method, body) {
    var r = await fetch(url, {method: method, headers: {'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined}), j = {};
    try { j = await r.json(); } catch (e) {}
    if (r.status === 401) { location.href = '/login'; return null; }
    if (!r.ok) { say(SF_I18N.msg(j) || T('common.error')); return null; }
    return j;
  }
  function draw() {
    var q = fold(Q.value), rows = cols.filter(function (c) { return fold(c.title).indexOf(q) >= 0; });
    L.innerHTML = '';
    if (!cols.length) return say(T('col.first'));
    if (!rows.length) return say(T('col.none'));
    rows.forEach(function (c) {
      var b = document.createElement('button'); b.type = 'button'; b.className = 'ca-row';
      b.innerHTML = '<img alt="" loading="lazy"><span class="ca-t"></span><span class="ca-n"></span>';
      b.firstChild.src = '/collection-poster/' + c.id; b.firstChild.onerror = function () { this.style.visibility = 'hidden'; };
      b.querySelector('.ca-t').textContent = c.title;
      b.querySelector('.ca-n').textContent = Tn('common.items', c.n);
      b.addEventListener('click', async function () {
        if (busy) return; busy = true;
        var j = await call('/admin/collections/' + c.id + '/items', 'POST', {media_ids: ids});
        busy = false;
        if (j) { close(); location.reload(); }
      });
      L.appendChild(b);
    });
  }
  async function create() {
    var t = N.value.trim().slice(0, 100);
    if (!t || busy) return;
    busy = true;
    var j = await call('/admin/collections', 'POST', {title: t, library_id: lib, media_ids: ids});
    busy = false;
    if (j) { close(); location.reload(); }
  }

  window.sfAddToCollection = async function (sel, kind, library, title) {
    ids = sel.slice(); lib = parseInt(library, 10);
    var titles = ids.map(function (i) {
      var a = document.querySelector('.pcard[data-pick="' + i + '"] .pcard-title'); return a ? a.textContent.trim() : '';
    }).filter(Boolean);
    if ((!titles.length || titles.length > 3) && title) titles = [title];  // muitos itens (barra da biblioteca): nome padrão = título dado
    Q.value = ''; N.value = titles.join(' ' + T('common.and') + ' ').slice(0, 100);
    el.querySelector('.em-head span').textContent = T('col.add_title'); el.querySelector('.em-x').setAttribute('aria-label', T('common.close'));
    Q.placeholder = T('col.search'); N.setAttribute('aria-label', T('col.name_aria')); OK.textContent = T('common.create');
    say(T('common.loading')); el.hidden = false;
    var j = await call('/admin/collections?library=' + lib, 'GET');
    if (j) { cols = j.collections; draw(); }
    N.focus(); N.select();
  };

  Q.addEventListener('input', draw);
  OK.addEventListener('click', create);
  N.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); create(); } });
  el.querySelector('.em-x').addEventListener('click', close);
  el.addEventListener('mousedown', function (e) { if (e.target === el) close(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !el.hidden) { e.stopImmediatePropagation(); close(); } }, true);
})();
