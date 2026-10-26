// Menu ⋮ da biblioteca (29.5): Fixar/Desafixar e itens de admin (sem Aleatório; menu compacto).
// As ações de admin (29.6–29.10) se registram com sfLibMenu.on(chave, fn); item sem ação registrada não aparece.
(function () {
  var btn = document.querySelector('[data-lib-menu]');
  if (!btn) return;
  var id = btn.dataset.libId, name = btn.dataset.libName, type = btn.dataset.libType;
  var state = {pinned: true, scanning: false, scannedAt: null, users: []}, loaded = null, actions = {}, toastEl = null, toastT = null, timer = null;
  var notice = {hidden: true};  // 35.8: o aviso em texto saiu; o indicador é o círculo girando (scan-indicator.js)

  function toast(msg) {
    if (!toastEl) { toastEl = document.createElement('div'); toastEl.className = 'sel-toast'; document.body.appendChild(toastEl); }
    toastEl.textContent = msg; toastEl.hidden = false;
    clearTimeout(toastT); toastT = setTimeout(function () { toastEl.hidden = true; }, 3500);
  }

  function load() {
    loaded = fetch('/library/' + id + '/info').then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.ok ? r.json() : null;
    }).then(function (j) {
      if (j) { state.pinned = j.pinned; state.scanning = j.scanning; state.scannedAt = j.scanned_at; state.users = j.users || []; }
      notice.hidden = !state.scanning;
      if (state.scanning) poll();
      return state;
    }).catch(function () { return state; });
    return loaded;
  }

  // Enquanto examina: avisa na página e consulta a cada 3 s; ao terminar, atualiza a grade/fileiras e o contador sem recarregar tudo
  function poll() {
    if (timer) return;
    timer = setTimeout(async function () {
      timer = null;
      await load();
      if (!state.scanning) refreshView();
    }, 3000);
  }

  async function refreshView() {
    try {
      var r = await fetch(location.href, {headers: {Accept: 'text/html'}});
      if (!r.ok) return;
      var doc = new DOMParser().parseFromString(await r.text(), 'text/html');
      var cur = document.querySelectorAll('.content .carousel-track'), nw = doc.querySelectorAll('.content .carousel-track');
      if (cur.length || nw.length) {
        if (cur.length !== nw.length) { location.reload(); return; }
        cur.forEach(function (t, i) { t.innerHTML = nw[i].innerHTML; });
      } else {
        var a = document.querySelector('.content .pgrid, .content .empty'), b = doc.querySelector('.content .pgrid, .content .empty');
        if (a && b) a.replaceWith(document.importNode(b, true));
      }
      var c1 = document.querySelector('.lib-count'), c2 = doc.querySelector('.lib-count');
      if (c1 && c2) c1.textContent = c2.textContent;
      window.dispatchEvent(new Event('resize'));
    } catch (e) {}
  }

  async function examine() {
    if (state.scanning) { toast(T('lib.scan_running')); return; }
    var r;
    try {
      r = await fetch('/admin/libraries/' + id + '/examine', {method: 'POST', headers: {Accept: 'application/json'}});
    } catch (e) { toast(T('lib.no_conn')); return; }
    if (r.status === 401) { location.href = '/login'; return; }
    var j = {}; try { j = await r.json(); } catch (e) {}
    if (!r.ok && r.status !== 409) { toast(SF_I18N.msg(j) || T('lib.scan_fail')); return; }
    state.scanning = true; notice.hidden = false;
    poll();
  }

  // Conceder Acesso… (29.7): modal sfLibAccess (27.3) com esta biblioteca já marcada
  async function access() {
    var r;
    try { r = await fetch('/admin/access/data', {headers: {Accept: 'application/json'}}); } catch (e) { toast(T('lib.no_conn')); return; }
    if (r.status === 401) { location.href = '/login'; return; }
    if (!r.ok || !window.sfLibAccess) { toast(T('lib.access_open_fail')); return; }
    var d = {}; try { d = await r.json(); } catch (e) {}
    window.sfLibAccess.open(null, d, {lib: parseInt(id, 10)});
  }
  // Editar… (29.8): modal da 28.13 na própria página; salvar recarrega
  async function edit() {
    var r;
    try { r = await fetch('/admin/libraries/data', {headers: {Accept: 'application/json'}}); } catch (e) { toast(T('lib.no_conn')); return; }
    if (r.status === 401) { location.href = '/login'; return; }
    var d = {}; try { d = await r.json(); } catch (e) {}
    var lib = (d.libraries || []).filter(function (l) { return String(l.id) === String(id); })[0];
    if (!r.ok || !lib || !window.sfLibEdit) { toast(T('lib.edit_open_fail')); return; }
    window.sfLibEdit.open(lib, d);
  }
  // Excluir (29.9): modal Apagar Biblioteca; depois vai ao Início
  function del() {
    if (!window.sfLibDelete) { toast(T('lib.delete_open_fail')); return; }
    window.sfLibDelete.open({id: id, name: name}, function () { location.href = '/'; });
  }
  document.addEventListener('la:saved', function () { toast(T('lib.access_updated')); });

  function fold(s) { return (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase(); }

  // Barra lateral sem recarregar: remove ou recoloca a biblioteca na ordem por nome
  function syncSidebar(pinned) {
    var nav = document.querySelector('#sidebar .nav');
    if (!nav) return;
    var cur = nav.querySelector('a.nav-item[href="/library/' + id + '"]');
    if (!pinned) { if (cur) cur.remove(); return; }
    if (cur) return;
    var a = document.createElement('a');
    a.href = '/library/' + id; a.className = 'nav-item active'; a.title = name; a.draggable = true;
    a.innerHTML = '<svg class="ic ic-lg"><use href="#' + (type === 'movie' ? 'i-film' : type === 'video' ? 'i-video' : 'i-tv') + '"/></svg><span class="nav-label"></span>';
    a.querySelector('.nav-label').textContent = name;
    var libs = [].slice.call(nav.querySelectorAll('a.nav-item[href^="/library/"]')), before = null;
    for (var i = 0; i < libs.length; i++) {
      if (fold(libs[i].title) > fold(name)) { before = libs[i]; break; }
    }
    if (before) nav.insertBefore(a, before);
    else if (libs.length) libs[libs.length - 1].after(a);
    else nav.querySelector('a.nav-item[href="/"]').after(a);
  }

  async function togglePin() {
    var want = !state.pinned, r;
    try {
      r = await fetch('/library/' + id + '/pin', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({pinned: want})});
    } catch (e) { toast(T('lib.no_conn')); return; }
    if (r.status === 401) { location.href = '/login'; return; }
    var j = {}; try { j = await r.json(); } catch (e) {}
    if (!r.ok) { toast(SF_I18N.msg(j) || T('lib.action_failed')); return; }
    state.pinned = want;
    syncSidebar(want);
  }

  function items() {
    var out = [{l: T(state.pinned ? 'lib.unpin' : 'lib.pin'), fn: togglePin}];
    if (window.sfAdmin) {
      if (actions.examine) out.push({l: T(state.scanning ? 'lib.examining' : 'lib.examine'), fn: actions.examine});
      if (actions.access) out.push({l: T('lib.grant_access'), fn: actions.access});
      var sub = [];
      [['edit', 'lib.edit'], ['refresh', 'lib.refresh_all'], ['trash', 'lib.empty_trash'], ['analyze', 'lib.analyze'], ['trickplay', 'lib.gen_thumbs'], ['optimize', 'lib.optimize'], ['delete', 'lib.delete']].forEach(function (k) {
        if (type === 'video' && k[0] === 'refresh') return;  // 34.6: sem metadados externos
        if (actions[k[0]]) sub.push({l: T(k[1]), fn: actions[k[0]]});
      });
      if (sub.length) out.push({l: T('lib.manage'), sub: sub});
    }
    return out;
  }

  // stopPropagation: o clique no documento (menu.js) fecharia o menu recém-aberto
  btn.addEventListener('click', async function (e) {
    e.stopPropagation();
    var kb = e.detail === 0;
    if (!window.sfMenuAt) return;
    if (!loaded) await load(); else load();
    window.sfMenuAt(btn, items(), kb, 'ctx-compact');
  });

  window.sfLibMenu = {
    id: id, name: name, type: type, state: state, toast: toast, reload: load,
    on: function (k, fn) { actions[k] = fn; },
    started: function () { state.scanning = true; notice.hidden = false; poll(); },
    refreshView: refreshView
  };
  actions.examine = examine;
  if (window.sfAdmin) { actions.access = access; actions.edit = edit; actions['delete'] = del; }
  load();
})();
