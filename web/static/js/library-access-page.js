(window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () {
  'use strict';
  var list = document.getElementById('la-list'), add = document.getElementById('la-add');
  if (!list) return;
  var data = null;

  function el(t, c, x) { var e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; }
  function count(n) { return Tn('pn.libs', n); }
  function msg(t) { list.textContent = ''; list.appendChild(el('p', 'la-empty', t)); }
  function open(u) { if (window.sfLibAccess) window.sfLibAccess.open(u || null, data); }

  function render() {
    var users = data.users.filter(function (u) { return u.libraries.length > 0; });
    if (!users.length) { msg(T('la.none')); return; }
    list.textContent = '';
    users.forEach(function (u) {
      var name = u.full_name || u.username;
      var row = el('div', 'la-row'); row.tabIndex = 0; row.setAttribute('role', 'button');
      var img = el('img', 'la-av'); img.src = '/avatar/' + u.id; img.alt = '';
      var who = el('div', 'la-who'); who.appendChild(el('div', 'la-name', name));
      if (u.full_name) who.appendChild(el('div', 'la-user', u.username));
      row.appendChild(img); row.appendChild(who);
      row.appendChild(el('div', 'la-count', T('la.count', {name: name, libs: count(u.libraries.length)})));
      row.addEventListener('click', function () { open(u); });
      row.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(u); } });
      list.appendChild(row);
    });
  }

  // Usado pelo modal (27.3): atualiza a linha sem recarregar
  document.addEventListener('la:saved', function (e) {
    if (!data || !e.detail) return;
    var u = e.detail, i = data.users.findIndex(function (x) { return x.id === u.id; });
    if (i >= 0) data.users[i] = u; else data.users.push(u);
    data.users.sort(function (a, b) { return SF_I18N.fmt.compare(a.username, b.username) || a.id - b.id; });
    render();
  });

  fetch('/admin/access/data', { headers: { Accept: 'application/json' } }).then(function (r) {
    if (r.status === 401) { location.href = '/login'; return null; }
    if (!r.ok) throw new Error();
    return r.json();
  }).then(function (j) {
    if (!j) return;
    data = j; render();
    if (window.sfLibAccess) { add.hidden = false; add.addEventListener('click', function () { open(null); }); }
    // /admin/access?user=<id> (link "Acesso" de Usuários): abre direto no passo 2
    var m = /[?&]user=([0-9]{1,18})(?:&|$)/.exec(location.search);
    if (m && window.sfLibAccess) {
      var u = data.users.find(function (x) { return x.id === +m[1]; });
      if (u) open(u);
      history.replaceState(null, '', location.pathname);
    }
  }).catch(function () { msg(T('la.load_fail')); });
});
