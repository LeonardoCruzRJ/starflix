// Página da lista de reprodução (31.9): Aleatório, menu ⋮ da lista e menu ⋮ de cada linha (fila, remover, excluir).
(function () {
  var P = window.sfPlaylist; if (!P) return;
  var toastEl = null, toastT = null;
  function toast(msg) {
    if (!toastEl) { toastEl = document.createElement('div'); toastEl.className = 'sel-toast'; document.body.appendChild(toastEl); }
    toastEl.textContent = msg; toastEl.hidden = false;
    clearTimeout(toastT); toastT = setTimeout(function () { toastEl.hidden = true; }, 3500);
  }
  function playUrl(id) { return P.kind === 'movie' ? '/watch/movie/' + id : '/show/' + id; }
  async function enqueue(ids, first) {
    var r = await fetch('/bulk/queue', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ids: ids})}), j = {};
    try { j = await r.json(); } catch (e) {}
    if (r.status === 401) { location.href = '/login'; return; }
    if (!r.ok || !window.sfQueue) { toast(SF_I18N.msg(j) || T('lib.action_failed')); return; }
    if (!j.items.length) { toast(T('pl.nothing_to_play')); return; }
    if (first) sfQueue.next(j.items); else sfQueue.add(j.items);
    toast(Tn(first ? 'lib.queued_next' : 'lib.queued_add', j.n));
  }
  async function removeItem(id, row) {
    var r = await fetch('/playlists/' + P.id + '/items/' + id, {method: 'DELETE'});
    if (r.status === 401) { location.href = '/login'; return; }
    if (r.ok) location.reload(); else toast(T('pl.remove_failed'));
  }

  var rnd = document.getElementById('pl-random');
  if (rnd) rnd.addEventListener('click', function () {
    if (P.ids.length) location.href = playUrl(P.ids[Math.floor(Math.random() * P.ids.length)]);
  });
  var ed = document.getElementById('pl-edit');
  if (ed) ed.addEventListener('click', function () { if (window.sfPlaylistEdit) sfPlaylistEdit(P.id); });

  var more = document.getElementById('pl-more');
  if (more) more.addEventListener('click', function (e) {
    e.stopPropagation();
    var items = [];
    if (P.ids.length) items.push({l: T('lib.play_next'), fn: function () { enqueue(P.ids, true); }}, {l: T('lib.add_queue'), fn: function () { enqueue(P.ids, false); }}, {sep: 1});
    items.push({l: T('det.copy_link'), copy: ''}, {l: T('lib.delete'), fn: function () { sfPlaylistDelete(P.id, P.name, '/library/' + P.library); }});
    window.sfMenuAt(more, items, false, 'ctx-right');
  });

  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-rowmenu]'); if (!b) return;
    e.preventDefault(); e.stopPropagation();
    var row = b.closest('.pl-row'), id = parseInt(row.dataset.id, 10);
    var items = [{l: T('card.play'), h: playUrl(id)}, {l: T('lib.play_next'), fn: function () { enqueue([id], true); }},
                 {l: T('lib.add_queue'), fn: function () { enqueue([id], false); }}];
    if (!P.smart) items.push({sep: 1}, {l: T('pl.remove_from'), fn: function () { removeItem(id, row); }});
    window.sfMenuAt(b, items, false, 'ctx-right');
  });
})();
