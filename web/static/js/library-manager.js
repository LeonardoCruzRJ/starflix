// Página /admin/libraries (28.9): lista, examinar, excluir e "Mesclar Itens Recentemente Adicionados" sem recarregar.
// Ganchos para as próximas etapas: window.sfLibWizard.open(data) (28.10) e window.sfLibEdit.open(lib, data) (28.13).
(window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () {
  'use strict';
  var list = document.getElementById('lm-list');
  if (!list) return;
  var cnt = document.getElementById('lm-count'), scanBtn = document.getElementById('lm-scan'),
      addBtn = document.getElementById('lm-add'), merge = document.getElementById('lm-merge');
  var NS = 'http://www.w3.org/2000/svg', data = null, timer = null;

  function el(t, c, x) { var e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; }
  function icon(id) { var s = document.createElementNS(NS, 'svg'); s.setAttribute('class', 'ic'); var u = document.createElementNS(NS, 'use'); u.setAttribute('href', '#' + id); s.appendChild(u); return s; }
  function api(url, body) {
    var o = { headers: { Accept: 'application/json' } };
    if (body !== undefined) { o.method = 'POST'; o.headers['Content-Type'] = 'application/json'; o.body = JSON.stringify(body); }
    return fetch(url, o).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return Promise.reject(); }
      return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) throw new Error(SF_I18N.msg(j) || T('common.error')); return j; });
    });
  }
  function msg(t) { list.textContent = ''; list.appendChild(el('p', 'la-empty', t)); }

  function actBtn(tip, ic, fn, hidden) {
    var b = el('button'); b.type = 'button'; b.setAttribute('data-tip', tip); b.setAttribute('aria-label', tip); b.hidden = !!hidden;
    b.appendChild(icon(ic));
    b.addEventListener('click', function (e) { e.stopPropagation(); fn(); });
    return b;
  }

  function render() {
    var n = data.libraries.length;
    cnt.textContent = Tn('pn.libs', n);
    scanBtn.disabled = !!data.scanning;
    scanBtn.textContent = data.scanning ? T('lib.examining') : T('lib.examine');
    addBtn.hidden = !window.sfLibWizard;
    merge.checked = !!data.settings.merge_recent;
    if (!n) { msg(T('pn.no_libs')); return; }
    list.textContent = '';
    data.libraries.forEach(function (l) {
      var row = el('div', 'lm-row'); row.tabIndex = 0;
      row.appendChild(icon(l.type === 'show' ? 'i-tv' : l.type === 'video' ? 'i-video' : 'i-film'));
      row.appendChild(el('div', 'lm-name', l.name));
      var acts = el('div', 'lm-acts');
      acts.appendChild(actBtn(T('pn.scan_one'), 'i-refresh', function () { scan('/admin/libraries/' + l.id + '/examine'); }));
      acts.appendChild(actBtn(T('common.edit'), 'i-edit', function () { edit(l); }, !window.sfLibEdit));
      acts.appendChild(actBtn(T('lib.delete'), 'i-trash', function () { confirmDelete(l); }));
      row.appendChild(acts);
      row.addEventListener('click', function () { edit(l); });
      row.addEventListener('keydown', function (e) { if (e.target === row && e.key === 'Enter') edit(l); });
      list.appendChild(row);
    });
  }

  function edit(l) { if (window.sfLibEdit) window.sfLibEdit.open(l, data); }

  function poll() {
    clearTimeout(timer);
    if (data && data.scanning) timer = setTimeout(load, 3000);
  }
  function load() {
    return api('/admin/libraries/data').then(function (j) { data = j; render(); poll(); })
      .catch(function () { if (!data) msg(T('lm.load_fail')); });
  }
  function scan(url) {
    data.scanning = true; render();
    api(url, {}).then(poll).catch(function () { load(); });
    setTimeout(load, 1500);
  }

  // Excluir: modal Apagar Biblioteca (29.9, library-delete.js)
  function confirmDelete(l) {
    if (!window.sfLibDelete) return;
    window.sfLibDelete.open(l, function () {
      data.libraries = data.libraries.filter(function (x) { return x.id !== l.id; });
      render();
    });
  }

  scanBtn.addEventListener('click', function () { scan('/admin/libraries/examine'); });
  addBtn.addEventListener('click', function () { if (window.sfLibWizard) window.sfLibWizard.open(data); });
  merge.addEventListener('change', function () {
    var v = merge.checked;
    api('/admin/libraries/settings', { merge_recent: v }).then(function (j) { data.settings.merge_recent = j.merge_recent; })
      .catch(function () { merge.checked = !v; });
  });

  window.sfLibManager = { reload: load, data: function () { return data; } };
  load();
});
