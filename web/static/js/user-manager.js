// Página /admin/users: lista de usuários, modal Adicionar/Editar e Remover (mesmo padrão de /admin/libraries).
(window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () {
  'use strict';
  var list = document.getElementById('um-list');
  if (!list) return;
  var cnt = document.getElementById('um-count'), addBtn = document.getElementById('um-add');
  var NS = 'http://www.w3.org/2000/svg', data = null;

  function el(t, c, x) { var e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; }
  function icon(id) { var s = document.createElementNS(NS, 'svg'); s.setAttribute('class', 'ic'); var u = document.createElementNS(NS, 'use'); u.setAttribute('href', '#' + id); s.appendChild(u); return s; }
  function api(url, body) {
    var o = { headers: { Accept: 'application/json' } };
    if (body !== undefined) { o.method = 'POST'; o.headers['Content-Type'] = 'application/json'; o.body = JSON.stringify(body); }
    return fetch(url, o).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return Promise.reject(new Error(T('common.session'))); }
      return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) throw new Error(SF_I18N.msg(j) || T('common.error')); return j; });
    });
  }
  function msg(t) { list.textContent = ''; list.appendChild(el('p', 'la-empty', t)); }
  function nlib(n) { return Tn('pn.libs', n); }
  function label(u) { return u.full_name || u.username; }

  function actBtn(tip, ic, fn, hidden) {
    var b = el('button'); b.type = 'button'; b.setAttribute('data-tip', tip); b.setAttribute('aria-label', tip); if (hidden) { b.className = 'um-ph'; b.disabled = true; b.tabIndex = -1; }  // mantém o espaço: colunas alinhadas
    b.appendChild(icon(ic));
    b.addEventListener('click', function (e) { e.stopPropagation(); fn(); });
    return b;
  }

  function render() {
    var n = data.users.length;
    cnt.textContent = Tn('um.count', n);
    if (!n) { msg(T('um.none')); return; }
    list.textContent = '';
    data.users.forEach(function (u) {
      var row = el('div', 'lm-row'); row.tabIndex = 0;
      var img = el('img', 'um-av'); img.src = '/avatar/' + u.id; img.alt = '';
      var who = el('div', 'um-who'); who.appendChild(el('div', 'lm-name', label(u)));
      if (u.full_name) who.appendChild(el('div', 'um-user', u.username));
      row.appendChild(img); row.appendChild(who);
      row.appendChild(el('div', 'um-role', u.is_admin ? T('um.admin') : T('um.access_to', {libs: nlib(u.libraries)})));
      var acts = el('div', 'lm-acts');
      acts.appendChild(actBtn(T('um.tip.access'), 'i-lock', function () { location.href = '/admin/access?user=' + u.id; }, u.is_admin));
      acts.appendChild(actBtn(T('common.edit'), 'i-edit', function () { openEdit(u); }));
      acts.appendChild(actBtn(T('common.remove'), 'i-trash', function () { openDelete(u); }, u.id === data.me));
      row.appendChild(acts);
      row.addEventListener('click', function () { openEdit(u); });
      row.addEventListener('keydown', function (e) { if (e.target === row && e.key === 'Enter') openEdit(u); });
      list.appendChild(row);
    });
  }

  function upsert(u) {
    var i = data.users.findIndex(function (x) { return x.id === u.id; });
    if (i >= 0) data.users[i] = u; else data.users.push(u);
    data.users.sort(function (a, b) { return SF_I18N.fmt.compare(a.username, b.username) || a.id - b.id; });
    render();
  }

  // ---- modal Adicionar / Editar ----
  var ov = el('div', 'em-overlay'); ov.hidden = true;
  ov.innerHTML = '<div class="em-win em-small" role="dialog" aria-modal="true" aria-labelledby="um-t">' +
    '<div class="em-head"><span id="um-t"></span><button type="button" class="em-x" aria-label="' + T('common.close') + '">✕</button></div>' +
    '<div class="em-pane">' +
    '<div class="um-f" id="um-fu"><div class="em-lab">' + T('auth.username') + '</div><input type="text" class="em-q" id="um-u" autocomplete="off" autocapitalize="off" spellcheck="false"></div>' +
    '<div class="um-f"><div class="em-lab" id="um-pl">' + T('auth.password') + '</div><input type="password" class="em-q" id="um-p" autocomplete="new-password"></div>' +
    '<label class="ld-check"><input type="checkbox" id="um-a"><span>' + T('um.admin') + '</span></label></div>' +
    '<div class="em-foot"><span class="em-err" id="um-e"></span><button type="button" class="em-btn em-cancel" id="um-c">' + T('common.cancel') + '</button>' +
    '<button type="button" class="em-btn em-save" id="um-s" disabled></button></div></div>';
  document.body.appendChild(ov);
  var q = function (s) { return ov.querySelector(s); };
  var title = q('#um-t'), fu = q('#um-fu'), iu = q('#um-u'), ip = q('#um-p'), ia = q('#um-a'), pl = q('#um-pl'),
      err = q('#um-e'), sv = q('#um-s'), editing = null, busy = false;

  function valid() {
    if (editing) return (ip.value !== '' || ia.checked !== editing.is_admin) && (ip.value === '' || ip.value.length >= 4);
    return iu.value.trim() !== '' && ip.value.length >= 4;
  }
  function check() { sv.disabled = busy || !valid(); }
  function closeEdit() { if (busy) return; ov.hidden = true; editing = null; }
  function show(u) {
    editing = u; err.textContent = ''; ip.value = ''; iu.value = '';
    fu.hidden = !!u; sv.textContent = u ? T('common.save_changes') : T('common.add');
    title.textContent = u ? T('um.edit_title', {name: label(u)}) : T('um.add');
    pl.textContent = u ? T('um.new_pass') : T('um.pass_min');
    ia.checked = u ? u.is_admin : false; ia.disabled = !!u && u.id === data.me;
    ov.hidden = false; check(); (u ? ip : iu).focus();
  }
  function openEdit(u) { show(u); }
  function openAdd() { show(null); }

  [iu, ip, ia].forEach(function (i) {
    i.addEventListener('input', check); i.addEventListener('change', check);
    i.addEventListener('keydown', function (e) { if (e.key === 'Enter' && !sv.disabled) sv.click(); });
  });
  q('.em-x').addEventListener('click', closeEdit);
  q('#um-c').addEventListener('click', closeEdit);
  ov.addEventListener('mousedown', function (e) { if (e.target === ov) closeEdit(); });
  sv.addEventListener('click', function () {
    if (busy || !valid()) return;
    busy = true; sv.disabled = true; err.textContent = '';
    var req = editing
      ? api('/admin/users/' + editing.id + '/edit', { password: ip.value, is_admin: ia.checked })
      : api('/admin/users', { username: iu.value.trim(), password: ip.value, is_admin: ia.checked });
    req.then(function (j) { busy = false; ov.hidden = true; editing = null; upsert(j.user); })
      .catch(function (e) { busy = false; err.textContent = e.message || T('common.save_failed'); check(); });
  });

  // ---- modal Remover usuário ----
  var dv = el('div', 'em-overlay'); dv.hidden = true;
  dv.innerHTML = '<div class="em-win em-small" role="dialog" aria-modal="true" aria-labelledby="ud-t">' +
    '<div class="em-head"><span id="ud-t">' + T('um.del.title') + '</span><button type="button" class="em-x" aria-label="' + T('common.close') + '">✕</button></div>' +
    '<div class="em-pane"><p class="ld-text"></p><label class="ld-check"><input type="checkbox" id="ud-ck"><span></span></label></div>' +
    '<div class="em-foot"><span class="em-err" id="ud-e"></span><button type="button" class="em-btn em-cancel" id="ud-c">' + T('common.cancel') + '</button>' +
    '<button type="button" class="em-btn em-danger" id="ud-x" disabled>' + T('common.remove') + '</button></div></div>';
  document.body.appendChild(dv);
  var dtxt = dv.querySelector('.ld-text'), dlbl = dv.querySelector('.ld-check span'), dck = dv.querySelector('#ud-ck'),
      derr = dv.querySelector('#ud-e'), dx = dv.querySelector('#ud-x'), du = null, dbusy = false;

  function closeDel() { if (dbusy) return; dv.hidden = true; du = null; }
  function openDelete(u) {
    du = u; derr.textContent = ''; dck.checked = false; dx.disabled = true;
    dtxt.textContent = T('um.del.text', {name: label(u)});
    dlbl.textContent = T('um.del.check', {name: label(u)});
    dv.hidden = false; dck.focus();
  }
  dck.addEventListener('change', function () { dx.disabled = !dck.checked; });
  dv.querySelector('.em-x').addEventListener('click', closeDel);
  dv.querySelector('#ud-c').addEventListener('click', closeDel);
  dv.addEventListener('mousedown', function (e) { if (e.target === dv) closeDel(); });
  dx.addEventListener('click', function () {
    if (!du || !dck.checked || dbusy) return;
    dbusy = true; dx.disabled = true; derr.textContent = '';
    var u = du;
    api('/admin/users/' + u.id + '/delete?json=1', {}).then(function () {
      dbusy = false; dv.hidden = true; du = null;
      data.users = data.users.filter(function (x) { return x.id !== u.id; }); render();
    }).catch(function (e) { dbusy = false; dx.disabled = !dck.checked; derr.textContent = e.message || T('common.remove_failed'); });
  });

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    if (!dv.hidden) closeDel(); else if (!ov.hidden) closeEdit();
  });
  addBtn.addEventListener('click', openAdd);

  api('/admin/users/data').then(function (j) { data = j; addBtn.hidden = false; render(); })
    .catch(function () { msg(T('um.load_fail')); });
});
