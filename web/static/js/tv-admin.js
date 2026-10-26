// 40.4: /admin/users — TVs conectadas de todos os usuários, com Revogar.
(window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () {
  'use strict';
  var list = document.getElementById('tva-list'), cnt = document.getElementById('tva-count');
  if (!list) return;
  var NS = 'http://www.w3.org/2000/svg';

  function el(t, c, x) { var e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; }
  function api(url, post) {
    var o = { headers: { Accept: 'application/json' } };
    if (post) o.method = 'POST';
    return fetch(url, o).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return Promise.reject(new Error(T('common.session'))); }
      return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) throw new Error(SF_I18N.msg(j) || T('common.error')); return j; });
    });
  }
  function msg(t) { list.textContent = ''; list.appendChild(el('p', 'la-empty', t)); }

  function render(devs) {
    cnt.textContent = Tn('tva.count', devs.length);
    if (!devs.length) { msg(T('tva.none')); return; }
    list.textContent = '';
    devs.forEach(function (d) {
      var row = el('div', 'lm-row');
      var who = el('div', 'um-who');
      who.appendChild(el('div', 'lm-name', d.name));
      who.appendChild(el('div', 'um-user', T('tva.info', {user: d.user, created: d.created}) + (d.seen && d.seen !== d.created ? T('tva.seen', {seen: d.seen}) : '')));
      row.appendChild(who);
      var acts = el('div', 'lm-acts');
      var b = el('button'); b.type = 'button'; b.setAttribute('data-tip', T('common.revoke')); b.setAttribute('aria-label', T('dev.revoke_aria', {name: d.name}));
      var s = document.createElementNS(NS, 'svg'); s.setAttribute('class', 'ic');
      var u = document.createElementNS(NS, 'use'); u.setAttribute('href', '#i-trash'); s.appendChild(u); b.appendChild(s);
      b.addEventListener('click', function () {
        sfConfirm(T('tva.revoke_q', {name: d.name, user: d.user}), {title: T('tva.revoke_title'), ok: T('common.revoke'), danger: true}).then(function (ok) {
          if (!ok) return;
          b.disabled = true;
          api('/admin/tv/devices/' + d.id + '/revoke', true).then(load, function (e) { b.disabled = false; alert(e.message); });
        });
      });
      acts.appendChild(b); row.appendChild(acts); list.appendChild(row);
    });
  }
  function load() { api('/admin/tv/devices').then(function (j) { render(j.devices || []); }, function (e) { msg(e.message); }); }
  load();
});
