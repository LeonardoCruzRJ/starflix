// Barra de seleção múltipla (24.4): ações em lote sobre os cards marcados (select.js avisa por "sf:selection").
// Rotas: POST /bulk/<watched|list|unresume|analyze|refresh|delete> {ids}. Ações de admin só existem no menu do admin.
(window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () {
  var bar = document.getElementById('sel-bar');
  if (!bar) return;
  var kind = bar.dataset.kind, ids = [], lbl = document.getElementById('sel-lbl');
  var toastEl = null, toastT = null;

  function toast(msg) {
    if (!toastEl) { toastEl = document.createElement('div'); toastEl.className = 'sel-toast'; document.body.appendChild(toastEl); }
    toastEl.textContent = msg; toastEl.hidden = false;
    clearTimeout(toastT); toastT = setTimeout(function () { toastEl.hidden = true; }, 3500);
  }
  function cardOf(id) { return document.querySelector('.pcard[data-pick="' + id + '"]'); }
  // Início (32.10): a barra não tem tipo/biblioteca fixos; vêm dos cards marcados (data-type / data-lib)
  function kindOf(id) {
    if (kind) return kind;
    var c = cardOf(id);
    var t = c ? (c.dataset.type || (c.classList.contains('pcard-t-show') ? 'show' : 'movie')) : 'movie';
    return t === 'video' ? 'movie' : t;  // 34.7: vídeo se comporta como filme na seleção
  }
  function libOf() {
    if (bar.dataset.library) return bar.dataset.library;
    var libs = ids.map(function (i) { var c = cardOf(i); return c ? c.dataset.lib || '' : ''; });
    return libs.length && libs.every(function (l) { return l && l === libs[0]; }) ? libs[0] : '';
  }
  function allWatched() {
    return ids.length > 0 && ids.every(function (i) { var c = cardOf(i); return c && c.querySelector('.pcard-seen'); });
  }
  async function post(op, body) {
    var r = await fetch('/bulk/' + op, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(Object.assign({ids: ids}, body || {}))}), j = {};
    try { j = await r.json(); } catch (e) {}
    if (r.status === 401) { location.href = '/login'; return null; }
    if (!r.ok) { toast(SF_I18N.msg(j) || T('common.action_failed')); return null; }
    return j;
  }
  async function reloading(op, body) { if (await post(op, body)) location.reload(); }
  function pick(list) { return list[Math.floor(Math.random() * list.length)]; }
  function link(id) { var c = cardOf(id), a = c && c.querySelector('.pcard-title'); return a ? a.getAttribute('href') : '/' + kindOf(id) + '/' + id; }

  function refreshBar() {
    var n = ids.length;
    lbl.textContent = Tn('bb.sel', n);
    var w = bar.querySelector('[data-act="watched"]'), t = allWatched() ? T('card.mark_unwatched') : T('card.mark_watched');
    w.dataset.tip = t; w.setAttribute('aria-label', t);
    var e = bar.querySelector('[data-act="edit"]');
    if (e) e.hidden = n !== 1;
  }
  document.addEventListener('sf:selection', function (e) { ids = e.detail.ids; refreshBar(); });

  var ACT = {
    play: function () {
      var id = ids[0];
      location.href = kindOf(id) === 'movie' ? '/watch/movie/' + id : '/show/' + id;
    },
    list: function () { reloading('list'); },
    watched: function () { reloading('watched', {watched: !allWatched()}); },
    addto: function (btn) {
      var items = [], lib = libOf();
      if (!lib) { toast(T('bb.same_lib')); return; }
      if (window.sfAdmin) items.push({l: T('lib.add_collection'), fn: function () {
        if (window.sfAddToCollection) window.sfAddToCollection(ids.slice(), kindOf(ids[0]), lib); else toast(T('bb.soon'));
      }}, {sep: 1});
      items.push({l: T('lib.add_playlist'), fn: function () {
        if (window.sfAddToPlaylist) window.sfAddToPlaylist(ids.slice(), kindOf(ids[0]), lib);
      }});
      window.sfMenuAt(btn, items);
    },
    edit: function () { if (ids.length === 1 && window.sfEditOpen) window.sfEditOpen(kindOf(ids[0]), String(ids[0])); },
    clear: function () { window.sfSelect.clear(); },
    more: function (btn) {
      var items = [{l: T('lib.shuffle'), fn: function () {
        var id = pick(ids);
        location.href = kindOf(id) === 'movie' ? '/watch/movie/' + id : '/show/' + id + '/random';
      }}, {l: T('bb.unresume'), fn: function () { reloading('unresume'); }}];
      if (window.sfAdmin && window.sfCollection) {
        items.push({l: T('mn.remove_col'), fn: function () { window.sfRemoveFromCollection(ids.slice()); }}, {sep: 1});
      }
      if (window.sfAdmin) {
        items.push({l: T('lib.refresh_info'), fn: async function () {
          var j = await post('refresh'); if (j) toast(Tn('bb.refreshing', j.n));
        }}, {l: T('lib.analyze'), fn: async function () {
          var j = await post('analyze'); if (j) toast(Tn('bb.analyzing', j.n));
        }}, {sep: 1}, {l: T('lib.delete'), fn: function () {
          window.sfItemAction({act: 'bulk-delete', ids: ids.slice(), kind: kindOf(ids[0])});
        }});
      }
      window.sfMenuAt(btn, items);
    }
  };
  bar.addEventListener('click', function (e) {
    var b = e.target.closest('[data-act]');
    if (b && ACT[b.dataset.act]) { e.stopPropagation(); ACT[b.dataset.act](b); }
  });
  refreshBar();
});
