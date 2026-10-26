// Modal "Adicionar biblioteca" (28.10: passo 1 — tipo, nome e idioma). window.sfLibWizard.open(data), data = /admin/libraries/data.
// Passo 2 (28.11): pastas via navegador (folder-picker.js). Passo 3 (28.12): library-adv.js.
(window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  var TYPES = [['movie', T('lm.type.movie'), 'i-film'], ['show', T('lm.type.show'), 'i-tv'], ['video', T('lm.type.video'), 'i-video']];
  var data, st, ov, win;
  function pane3(pane) { window.sfLibAdv.render(pane, st.prefs, data, function () {}, st.type); }

  function el(t, c, x) { var e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; }
  function icon(id, c) { var s = document.createElementNS(NS, 'svg'); s.setAttribute('class', 'ic ' + (c || '')); var u = document.createElementNS(NS, 'use'); u.setAttribute('href', '#' + id); s.appendChild(u); return s; }
  function dirty() { return !!st.type || st.folders.length > 0; }
  function close(force) {
    if (!force && dirty()) { sfConfirm(T('lm.discard_q'), {title: T('lm.discard_title'), ok: T('lm.discard'), danger: true}).then(function (ok) { if (ok) close(true); }); return; }
    ov.hidden = true; ov.textContent = ''; document.removeEventListener('keydown', onKey, true);
  }
  function onKey(e) { if (e.key === 'Escape') { e.stopImmediatePropagation(); close(); } }

  function pickType(t) {
    st.type = t[0];
    if (!st.nameEdited) st.name = t[1];
    draw();
  }

  function stepBtn(n, label, ic, enabled) {
    var b = el('button', 'lw-step' + (st.step === n ? ' active' : '')); b.type = 'button'; b.disabled = !enabled;
    b.appendChild(icon(ic, 'ic-sm')); b.appendChild(el('span', '', label));
    b.addEventListener('click', function () { st.step = n; draw(); });
    return b;
  }

  function pane1(pane) {
    pane.appendChild(el('div', 'lw-h', T('lm.w.pick_type')));
    var types = el('div', 'lw-types');
    TYPES.forEach(function (t) {
      var b = el('button', 'lw-type' + (st.type === t[0] ? ' on' : '')); b.type = 'button';
      b.appendChild(icon(t[2], 'ic-xl')); b.appendChild(el('span', '', t[1]));
      b.addEventListener('click', function () { pickType(t); });
      types.appendChild(b);
    });
    pane.appendChild(types);
    if (!st.type) return;
    var f = el('div', 'lw-fields');
    var a = el('label', 'lw-f'); a.appendChild(el('span', '', T('lm.w.name')));
    var name = el('input'); name.type = 'text'; name.maxLength = 100; name.value = st.name; name.autocomplete = 'off';
    name.addEventListener('input', function () { st.name = name.value; st.nameEdited = true; nextBtn(); });
    a.appendChild(name); f.appendChild(a); pane.appendChild(f);
  }

  function pane2(pane) {
    pane.appendChild(el('div', 'lw-h', T('lm.w.folders_h')));
    var pick = el('button', 'em-btn em-cancel lw-pick'); pick.type = 'button';
    pick.appendChild(icon('i-folder-plus', 'ic-sm')); pick.appendChild(el('span', '', T('lm.pick_folder')));
    pick.addEventListener('click', function () {
      window.sfFolderPicker.open({ folders: st.folders }, function (p) { if (st.folders.indexOf(p) < 0) st.folders.push(p); draw(); });
    });
    pane.appendChild(pick);
    pane.appendChild(el('p', 'lw-hint', st.type === 'video' ? T('lm.hint_video') : T('lm.hint_media')));
    if (!st.folders.length) return;
    var list = el('div', 'lw-folders');
    st.folders.forEach(function (p, i) {
      var r = el('div', 'lw-folder'); r.appendChild(icon('i-folder', 'ic-sm')); r.appendChild(el('span', '', p));
      var x = el('button', '', '✕'); x.type = 'button'; x.setAttribute('aria-label', T('lm.rm_folder'));
      x.addEventListener('click', function () { st.folders.splice(i, 1); draw(); });
      r.appendChild(x); list.appendChild(r);
    });
    pane.appendChild(list);
  }

  var nb;
  function nextBtn() {
    if (!nb) return;
    if (st.step === 1) { nb.textContent = T('common.next'); nb.disabled = !st.type || !st.name.trim(); }
    else { nb.textContent = T('lm.w.finish'); nb.disabled = st.saving || !st.folders.length; }
  }

  function save() {
    st.saving = true; nextBtn(); err.textContent = '';
    fetch('/admin/libraries/add', {
      method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ name: st.name.trim(), type: st.type, folders: st.folders, prefs: st.prefs })
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) throw new Error(SF_I18N.msg(j) || T('lm.w.fail')); return j; });
    }).then(function (j) {
      if (!j) return;
      close(true);
      if (window.sfLibManager) window.sfLibManager.reload();
    }).catch(function (e) { st.saving = false; err.textContent = e.message; nextBtn(); });
  }

  var err;
  function draw() {
    win.textContent = '';
    var head = el('div', 'em-head'); head.appendChild(icon('i-plus', 'ic-sm')); head.appendChild(el('span', '', T('lm.add')));
    var x = el('button', 'em-x', '✕'); x.type = 'button'; x.setAttribute('aria-label', T('common.close')); x.addEventListener('click', function () { close(); });
    head.appendChild(x); win.appendChild(head);
    var body = el('div', 'lw-body'), steps = el('nav', 'lw-steps');
    steps.appendChild(stepBtn(1, T('lm.step.type'), 'i-align-left', true));
    steps.appendChild(stepBtn(2, T('lm.step.folders'), 'i-folder-open', !!st.type && !!st.name.trim()));
    steps.appendChild(stepBtn(3, T('lm.step.adv'), 'i-gear', st.folders.length > 0));
    var pane = el('div', 'em-pane lw-pane');
    [0, pane1, pane2, pane3][st.step](pane);
    body.appendChild(steps); body.appendChild(pane); win.appendChild(body);
    var foot = el('div', 'em-foot'); err = el('span', 'em-err');
    var c = el('button', 'em-btn em-cancel', T('common.cancel')); c.type = 'button'; c.addEventListener('click', function () { close(); });
    nb = el('button', 'em-btn em-save'); nb.type = 'button';
    nb.addEventListener('click', function () { if (st.step === 1) { st.step = 2; draw(); } else save(); });
    foot.appendChild(err); foot.appendChild(c); foot.appendChild(nb); win.appendChild(foot);
    nextBtn();
  }

  window.sfLibWizard = {
    open: function (d) {
      data = d; st = { step: 1, type: null, name: '', nameEdited: false, folders: [], prefs: JSON.parse(JSON.stringify(d.defaults || {})), saving: false };
      if (!ov) { ov = el('div', 'em-overlay'); document.body.appendChild(ov); ov.addEventListener('mousedown', function (e) { if (e.target === ov) close(); }); }
      ov.textContent = ''; win = el('div', 'em-win lw-win'); win.setAttribute('role', 'dialog'); win.setAttribute('aria-modal', 'true'); ov.appendChild(win);
      ov.hidden = false; document.addEventListener('keydown', onKey, true); draw();
    }
  };
  var add = document.getElementById('lm-add');
  if (add) add.hidden = false;
});
