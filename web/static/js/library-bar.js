// Barra da biblioteca (30): filtros e ordenação em menus próprios, modo de exibição (Grelha), "Adicionar para…" e "⋯".
// Usa window.sfMenuAt (menu.js). Itens {off: 1} aparecem apagados (ação ainda sem backend). Ações sobre todos os itens da visualização.
(function () {
  var bar = document.getElementById('lib-bar');
  if (!bar) return;
  var kind = bar.dataset.kind, lib = bar.dataset.library, libName = bar.dataset.libName;
  var curSort = bar.dataset.sort, curDir = bar.dataset.dir;
  var toastEl = null, toastT = null;

  function toast(msg) {
    if (!toastEl) { toastEl = document.createElement('div'); toastEl.className = 'sel-toast'; document.body.appendChild(toastEl); }
    toastEl.textContent = msg; toastEl.hidden = false;
    clearTimeout(toastT); toastT = setTimeout(function () { toastEl.hidden = true; }, 3500);
  }
  function go(set) {
    var q = new URLSearchParams(location.search);
    q.set('tab', 'library');
    // parte do estado atual (pode vir do banco, não da URL) e aplica a mudança
    var cur = {sort: curSort, dir: curDir};
    [].forEach.call(bar.querySelectorAll('[data-dd="filter"],[data-dd="genre"]'), function (b) { cur[b.dataset.dd] = b.dataset.cur; });
    Object.keys(cur).forEach(function (k) { if (cur[k] && k !== 'tab') q.set(k, cur[k]); });
    Object.keys(set).forEach(function (k) { if (set[k] === null || set[k] === '') q.delete(k); else q.set(k, set[k]); });
    if (set.sort && !('dir' in set)) q.delete('dir');
    if (!q.has('filter') && !q.has('genre') && !q.has('sort')) q.set('sort', 'title');  // URL sempre explícita: "tudo padrão" não cai na escolha antiga salva
    // lembra a escolha deste perfil nesta biblioteca no servidor (banco), para valer em qualquer dispositivo;
    // só navega depois de gravar (com falha de rede, navega mesmo assim: a URL já traz a escolha)
    var saved = {};
    ['sort', 'dir', 'filter', 'genre'].forEach(function (k) { if (q.has(k)) saved[k] = q.get(k); });
    var url = location.pathname + '?' + q.toString();
    fetch('/library/' + lib + '/view-prefs', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(saved)})
      .catch(function () {})
      .then(function () { location.href = url; });
  }
  // cookie antigo (38.1): já foi importado para o banco pelo servidor; apaga do navegador
  try { document.cookie = 'sf_lib_' + document.documentElement.dataset.pid + '_' + lib + '=; path=/; max-age=0; samesite=lax'; } catch (e) {}
  function ids() {
    return [].map.call(document.querySelectorAll('.pcard[data-pick]:not([hidden])'), function (c) { return parseInt(c.dataset.pick, 10); });
  }
  async function post(op) {
    var list = ids();
    if (!list.length) { toast(T('lib.no_items')); return null; }
    var r = await fetch('/bulk/' + op, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ids: list})}), j = {};
    try { j = await r.json(); } catch (e) {}
    if (r.status === 401) { location.href = '/login'; return null; }
    if (!r.ok) { toast(SF_I18N.msg(j) || T('lib.action_failed')); return null; }
    return j;
  }
  // 31.9: fila (sfQueue, js/queue.js): "Reproduzir a seguir" vai para o início, "Adicionar à fila" para o fim
  async function enqueue(first) {
    var j = await post('queue');
    if (!j || !window.sfQueue) return;
    if (!j.items.length) { toast(T('lib.nothing_to_play')); return; }
    if (first) sfQueue.next(j.items); else sfQueue.add(j.items);
    toast(Tn(first ? 'lib.queued_next' : 'lib.queued_add', j.n));
  }
  function show(btn, items, right) {
    window.sfMenuAt(btn, items, false, 'ctx-lib' + (right ? ' ctx-right' : ''));
  }
  function parse(s, d) { try { return JSON.parse(s); } catch (e) { return d; } }

  // ---- filtros e ordenação ----
  function ddItems(b) {
    var which = b.dataset.dd, cur = b.dataset.cur;
    if (which === 'filter') {
      return parse(b.dataset.opts, []).map(function (o) {
        return {l: o[1], on: o[0] === cur, fn: function () { go({filter: o[0]}); }};
      });
    }
    if (which === 'genre') {
      var items = [{l: b.dataset.all, on: cur === '', fn: function () { go({genre: ''}); }}];
      parse(b.dataset.genres, []).forEach(function (g) { items.push({l: g, on: g === cur, fn: function () { go({genre: g}); }}); });
      return items;
    }
    return parse(b.dataset.opts, []).map(function (o) {  // ordenação: clicar no item ativo inverte o sentido
      var active = o[0] === curSort;
      return {l: o[1], on: active, r: active ? (curDir === 'asc' ? '↑' : '↓') : '',
              fn: function () { if (active) go({sort: o[0], dir: curDir === 'asc' ? 'desc' : 'asc'}); else go({sort: o[0], dir: ''}); }};
    });
  }

  // ---- ⋯ e Adicionar para… ----
  var LB = {
    addto: function (btn) {
      var items = [];
      if (window.sfAdmin) items.push({l: T('lib.add_collection'), fn: function () {
        var list = ids();
        if (!list.length) { toast(T('lib.no_items')); return; }
        if (window.sfAddToCollection) window.sfAddToCollection(list, kind, lib, libName);
      }}, {l: T('lib.smart_collection'), fn: function () { if (window.sfAdvFilter) window.sfAdvFilter.open('collection'); }}, {sep: 1});
      items.push({l: T('lib.add_playlist'), fn: function () {
        var list = ids();
        if (!list.length) { toast(T('lib.no_items')); return; }
        if (window.sfAddToPlaylist) window.sfAddToPlaylist(list, kind, lib, libName);
      }}, {l: T('lib.smart_playlist'), fn: function () { if (window.sfAdvFilter) window.sfAdvFilter.open('playlist'); }});
      show(btn, items, true);
    },
    more: function (btn) {
      var items = [{l: T('lib.play_next'), fn: function () { enqueue(true); }}, {l: T('lib.add_queue'), fn: function () { enqueue(false); }}];
      if (window.sfAdmin) {
        items.push({sep: 1}, {l: T('lib.refresh_info'), fn: async function () {
          var j = await post('refresh'); if (j) toast(Tn('lib.refreshing', j.n));
        }}, {l: T('lib.analyze'), fn: async function () {
          var j = await post('analyze'); if (j) toast(Tn('lib.analyzing', j.n));
        }});
      }
      show(btn, items, true);
    }
  };

  bar.addEventListener('click', function (e) {
    var d = e.target.closest('[data-dd]'), a = e.target.closest('[data-lb]');
    if (d) { e.stopPropagation(); show(d, ddItems(d), false); return; }
    if (a && LB[a.dataset.lb]) { e.stopPropagation(); LB[a.dataset.lb](a); }
  });

  // ---- modo de exibição (ao lado do zoom) ----
  var vb = document.querySelector('[data-view-menu]'), V = window.sfLibView || {get: function () { return 'grid'; }, set: function () {}};
  if (vb) {
    vb.addEventListener('click', function (e) {
      e.stopPropagation();
      show(vb, [
        {l: T('lib.view.grid'), on: V.get() === 'grid', fn: function () { V.set('grid'); }},
        {l: T('lib.view.detail'), on: V.get() === 'detail', fn: function () { V.set('detail'); }},
        {l: T('lib.view.table'), on: V.get() === 'table', fn: function () { V.set('table'); }}
      ], true);
    });
  }
})();
