// Página /tv: autoriza a TV pelo código digitado, lista as TVs conectadas e revoga.
(function () {
  'use strict';
  var form = document.getElementById('tv-form'), input = document.getElementById('tv-code'), msg = document.getElementById('tv-msg');
  var list = document.getElementById('tv-list'), none = document.getElementById('tv-none'), go = document.getElementById('tv-go');
  if (!form) return;

  function say(t, ok) { msg.hidden = !t; msg.textContent = t || ''; msg.className = 'tv-msg ' + (ok ? 'ok' : 'err'); }
  function api(url, body) {
    var o = { headers: { Accept: 'application/json' } };
    if (body !== undefined) { o.method = 'POST'; o.headers['Content-Type'] = 'application/json'; o.body = JSON.stringify(body); }
    return fetch(url, o).then(function (r) {
      if (r.status === 401) { location.href = '/login?next=/tv'; return Promise.reject(new Error(T('common.session'))); }
      return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) throw new Error(SF_I18N.msg(j) || T('common.error')); return j; });
    });
  }
  function clean(v) { return v.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 6); }

  function render(devs) {
    list.textContent = '';
    devs.forEach(function (d) {
      var li = document.createElement('li'); li.setAttribute('data-id', d.id);
      var n = document.createElement('span'); n.className = 'tv-name'; n.textContent = d.name;
      var w = document.createElement('span'); w.className = 'tv-when'; w.textContent = T('tvp.connected_at', {date: d.created}) + (d.seen && d.seen !== d.created ? ' · ' + T('dev.seen', {date: d.seen}) : '');
      var b = document.createElement('button'); b.type = 'button'; b.className = 'tv-rev'; b.textContent = T('common.revoke'); b.setAttribute('aria-label', T('dev.revoke_aria', {name: d.name}));
      li.appendChild(n); li.appendChild(w); li.appendChild(b); list.appendChild(li);
    });
    none.hidden = devs.length > 0;
  }
  function refresh() { return api('/tv/devices').then(function (j) { render(j.devices); }).catch(function () { /* mantém a lista */ }); }

  input.addEventListener('input', function () { var c = clean(input.value); if (c !== input.value) input.value = c; });
  input.addEventListener('paste', function (e) {
    var t = (e.clipboardData || window.clipboardData).getData('text');
    if (t) { e.preventDefault(); input.value = clean(t); }
  });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var c = clean(input.value);
    if (c.length !== 6) { say(T('tvp.code_len'), false); return; }
    go.disabled = true; say(T('tvp.authorizing'), true);
    api('/tv/authorize', { code: c }).then(function (j) {
      say(T('tvp.authorized', {name: j.name}), true);
      input.value = '';
      setTimeout(refresh, 3000); setTimeout(refresh, 8000);
    }).catch(function (err) { say(err.message, false); }).then(function () { go.disabled = false; });
  });

  list.addEventListener('click', function (e) {
    var b = e.target.closest('.tv-rev'); if (!b) return;
    var li = b.closest('li');
    sfConfirm(T('tvp.revoke_q'), {title: T('dev.revoke_title'), ok: T('common.revoke'), danger: true}).then(function (ok) {
      if (!ok) return;
      b.disabled = true;
      api('/tv/devices/' + li.getAttribute('data-id') + '/revoke', {}).then(function () { li.remove(); none.hidden = list.children.length > 0; })
        .catch(function (err) { b.disabled = false; say(err.message, false); });
    });
  });
  if (location.search) history.replaceState(null, '', '/tv');  // tira o código da barra de endereço

  // 58.13: só no app do celular (WebActivity expõe StarflixApp): abre o leitor para o QR que a TV mostra
  var scan = document.getElementById('tv-scan');
  if (scan && window.StarflixApp && typeof window.StarflixApp.scanTv === 'function') {
    scan.hidden = false;
    scan.addEventListener('click', function () { window.StarflixApp.scanTv(); });
  }
})();
