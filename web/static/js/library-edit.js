// Modal "Editar <nome>" (28.13, captura 94 na 29.8): abas Geral, Adicionar pastas e Avançado. window.sfLibEdit.open(lib, data).
// Salvar recarrega a página quando não há gerenciador de bibliotecas (página da biblioteca).
(window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  var data, lib, st, ov, win;

  function el(t, c, x) { var e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; }
  function icon(id, c) { var s = document.createElementNS(NS, 'svg'); s.setAttribute('class', 'ic ' + (c || '')); var u = document.createElementNS(NS, 'use'); u.setAttribute('href', '#' + id); s.appendChild(u); return s; }
  function same(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
  function changed() { return st.name !== lib.name || st.lang !== (lib.lang || 'pt-BR') || !same(st.folders, lib.folders) || !same(st.prefs, lib.prefs); }
  function metaChanged() { return st.lang !== (lib.lang || 'pt-BR') || st.prefs.cert_country !== lib.prefs.cert_country; }
  function close(force) {
    if (!force && changed()) { sfConfirm(T('lm.discard_q'), {title: T('lm.discard_title'), ok: T('lm.discard'), danger: true}).then(function (ok) { if (ok) close(true); }); return; }
    ov.hidden = true; ov.textContent = ''; document.removeEventListener('keydown', onKey, true);
  }
  function onKey(e) { if (e.key === 'Escape') { e.stopImmediatePropagation(); close(); } }
  var sv, warn, err;
  function refresh() { if (sv) sv.disabled = st.saving || !changed() || !st.name.trim() || !st.folders.length; if (warn) warn.hidden = !metaChanged(); }

  function tab(n, label, ic) {
    var b = el('button', 'lw-step' + (st.tab === n ? ' active' : '')); b.type = 'button';
    b.appendChild(icon(ic, 'ic-sm')); b.appendChild(el('span', '', label));
    b.addEventListener('click', function () { st.tab = n; draw(); });
    return b;
  }

  // "há 3 horas" no idioma ativo, a partir de um epoch em segundos
  function ago(ts) { return SF_I18N.fmt.agoTs(ts); }

  function paneGeral(pane) {
    pane.appendChild(el('div', 'lw-h lw-h-dim', T('lm.e.type_h')));
    var types = el('div', 'lw-types');
    [['movie', T('lm.type.movie'), 'i-film'], ['show', T('lm.type.show'), 'i-tv'], ['video', T('lm.type.video'), 'i-video']].forEach(function (t) {
      var on = t[0] === lib.type, b = el('button', 'lw-type' + (on ? ' on' : ' off')); b.type = 'button'; b.disabled = !on; b.tabIndex = -1;
      b.appendChild(icon(t[2], 'ic-xl')); b.appendChild(el('span', '', t[1]));
      types.appendChild(b);
    });
    pane.appendChild(types);
    pane.appendChild(el('div', 'lw-h', T('lm.e.name_h')));
    var f = el('div', 'lw-fields');
    var a = el('label', 'lw-f'); a.appendChild(el('span', '', T('lm.w.name')));
    var name = el('input'); name.type = 'text'; name.maxLength = 100; name.value = st.name; name.autocomplete = 'off';
    name.addEventListener('input', function () { st.name = name.value; refresh(); });
    a.appendChild(name); f.appendChild(a);
    var b = el('label', 'lw-f'); b.appendChild(el('span', '', T('common.language')));
    var sel = el('select');
    Object.keys(data.langs).forEach(function (k) { var o = el('option', '', data.langs[k]); o.value = k; if (k === st.lang) o.selected = true; sel.appendChild(o); });
    sel.addEventListener('change', function () { st.lang = sel.value; refresh(); });
    b.appendChild(sel); f.appendChild(b);
    pane.appendChild(f);
    pane.appendChild(el('p', 'lw-upd', lib.scanned_at ? T('lm.e.updated', {ago: ago(lib.scanned_at)}) : T('lm.e.never')));
  }

  function panePastas(pane) {
    var pick = el('button', 'em-btn em-cancel lw-pick'); pick.type = 'button';
    pick.appendChild(icon('i-folder-plus', 'ic-sm')); pick.appendChild(el('span', '', T('lm.pick_folder')));
    pick.addEventListener('click', function () {
      window.sfFolderPicker.open({ folders: st.folders, libraryId: lib.id }, function (p) { if (st.folders.indexOf(p) < 0) st.folders.push(p); draw(); });
    });
    pane.appendChild(pick);
    var list = el('div', 'lw-folders');
    st.folders.forEach(function (p, i) {
      var r = el('div', 'lw-folder'); r.appendChild(icon('i-folder', 'ic-sm')); r.appendChild(el('span', '', p));
      var x = el('button', '', '✕'); x.type = 'button'; x.setAttribute('aria-label', T('lm.rm_folder'));
      x.addEventListener('click', function () {
        var rm = function () { st.folders.splice(i, 1); draw(); };
        if (lib.folders.indexOf(p) < 0) { rm(); return; }
        sfConfirm(T('lm.e.rm_confirm'), {title: T('lm.rm_folder'), ok: T('common.remove'), danger: true}).then(function (ok) { if (ok) rm(); });
      });
      r.appendChild(x); list.appendChild(r);
    });
    pane.appendChild(list);
    if (!st.folders.length) pane.appendChild(el('p', 'lw-hint', T('lm.e.need_folder')));
  }

  function save() {
    st.saving = true; refresh(); err.textContent = '';
    var body = { name: st.name.trim(), lang: st.lang, prefs: st.prefs, folders: st.folders };
    fetch('/admin/libraries/' + lib.id + '/update', {
      method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify(body)
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) throw new Error(SF_I18N.msg(j) || T('common.save_failed')); return j; });
    }).then(function (j) {
      if (!j) return;
      close(true);
      if (window.sfLibManager) window.sfLibManager.reload(); else location.reload();
    }).catch(function (e) { st.saving = false; err.textContent = e.message; refresh(); });
  }

  function draw() {
    win.textContent = '';
    var head = el('div', 'em-head'); head.appendChild(icon('i-edit', 'ic-sm')); head.appendChild(el('span', '', T('lm.e.title', {name: lib.name})));
    var x = el('button', 'em-x', '✕'); x.type = 'button'; x.setAttribute('aria-label', T('common.close')); x.addEventListener('click', function () { close(); });
    head.appendChild(x); win.appendChild(head);
    var body = el('div', 'lw-body'), steps = el('nav', 'lw-steps');
    steps.appendChild(tab(1, T('lm.step.general'), 'i-align-left')); steps.appendChild(tab(2, T('lm.step.folders'), 'i-folder-open')); steps.appendChild(tab(3, T('lm.step.adv'), 'i-gear'));
    var pane = el('div', 'em-pane lw-pane');
    if (st.tab === 1) paneGeral(pane); else if (st.tab === 2) panePastas(pane);
    else window.sfLibAdv.render(pane, st.prefs, data, refresh, lib.type);
    body.appendChild(steps); body.appendChild(pane); win.appendChild(body);
    var foot = el('div', 'em-foot');
    warn = el('span', 'em-err', T('lm.e.meta')); warn.hidden = true;
    err = el('span', 'em-err');
    var c = el('button', 'em-btn em-cancel', T('common.cancel')); c.type = 'button'; c.addEventListener('click', function () { close(); });
    sv = el('button', 'em-btn em-save', T('common.save_changes')); sv.type = 'button'; sv.addEventListener('click', save);
    foot.appendChild(warn); foot.appendChild(err); foot.appendChild(c); foot.appendChild(sv); win.appendChild(foot);
    refresh();
  }

  window.sfLibEdit = {
    open: function (l, d) {
      data = d; lib = l;
      st = { tab: 1, name: l.name, lang: l.lang || 'pt-BR', folders: l.folders.slice(), prefs: JSON.parse(JSON.stringify(l.prefs)), saving: false };
      if (!ov) { ov = el('div', 'em-overlay'); document.body.appendChild(ov); ov.addEventListener('mousedown', function (e) { if (e.target === ov) close(); }); }
      ov.textContent = ''; win = el('div', 'em-win lw-win'); win.setAttribute('role', 'dialog'); win.setAttribute('aria-modal', 'true'); ov.appendChild(win);
      ov.hidden = false; document.addEventListener('keydown', onKey, true); draw();
    }
  };
});
