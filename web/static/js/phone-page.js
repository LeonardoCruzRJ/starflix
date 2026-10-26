// Página /phone: QR dinâmico (renova sozinho a cada ~45 s e na hora em que o celular usa), link de uso único e lista de celulares conectados.
(function () {
  'use strict';
  var box = document.getElementById('ph-qr'), bar = document.getElementById('ph-bar'), fill = document.getElementById('ph-fill');
  var msg = document.getElementById('ph-msg'), note = document.getElementById('ph-note');
  if (!box) return;
  var SHOW = 45000, POLL = 2000;          // tempo mostrado do QR e intervalo da consulta
  var cur = null, timer = null, poll = null, busy = false;

  function say(t, ok) { msg.hidden = !t; msg.textContent = t || ''; msg.className = 'tv-msg ' + (ok ? 'ok' : 'err'); }
  function api(url, post) {
    var o = { headers: { Accept: 'application/json' } };
    if (post) { o.method = 'POST'; o.headers['Content-Type'] = 'application/json'; o.body = '{}'; }
    return fetch(url, o).then(function (r) {
      if (r.status === 401) { location.href = '/login?next=/phone'; return Promise.reject(new Error(T('common.session'))); }
      return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) { var e = new Error(SF_I18N.msg(j) || T('common.error')); e.status = r.status; throw e; } return j; });
    });
  }
  function stop() { clearTimeout(timer); clearInterval(poll); fill.style.transition = 'none'; }

  function show(j) {
    stop(); cur = j.id;
    box.textContent = '';
    if (j.svg) { box.innerHTML = j.svg; var s = box.querySelector('svg'); if (s) { s.removeAttribute('width'); s.removeAttribute('height'); s.setAttribute('role', 'img'); s.setAttribute('aria-label', T('ph.qr_aria')); } }
    else { box.textContent = T('ph.qr_fail'); }
    note.hidden = !j.local;
    if (j.local) note.textContent = T('ph.local_note');
    bar.hidden = false; fill.style.transform = 'scaleX(1)'; void fill.offsetWidth;
    fill.style.transition = 'transform ' + SHOW + 'ms linear'; fill.style.transform = 'scaleX(0)';
    timer = setTimeout(renew, SHOW);
    poll = setInterval(check, POLL);
  }

  function renew() {
    if (busy) return; busy = true; stop();
    api('/phone/qr', true).then(function (j) { say(''); show(j); })
      .catch(function (e) { say(e.message, false); timer = setTimeout(renew, 10000); })
      .then(function () { busy = false; });
  }

  function check() {
    if (cur == null || document.hidden) return;
    api('/phone/token/' + cur).then(function (j) {
      if (j.status === 'used') { say(T('ph.connected', {name: j.name}), true); refresh(); setTimeout(renew, 1500); stop(); }
      else if (j.status === 'expired') renew();
    }).catch(function (e) { if (e.status === 404) renew(); });
  }

  // celular: o QR precisa ser lido por outro aparelho, então só o link fica (58.9)
  var mobile = window.matchMedia && window.matchMedia('(max-width: 700px)').matches;
  if (mobile) {
    box.hidden = true; document.getElementById('ph-qrhelp').hidden = true; document.getElementById('ph-mobile').hidden = false;
    document.querySelector('.ph-steps').hidden = true;
  } else {
    // aba em segundo plano não gasta pedidos: ao voltar, gera um QR novo
    document.addEventListener('visibilitychange', function () { if (document.hidden) stop(); else renew(); });
    renew();
  }

  // ---- link de uso único ----
  var linkGo = document.getElementById('ph-link-go'), linkBox = document.getElementById('ph-link'), linkUrl = document.getElementById('ph-link-url');
  var linkInfo = document.getElementById('ph-link-info'), copy = document.getElementById('ph-copy');
  linkGo.addEventListener('click', function () {
    linkGo.disabled = true;
    api('/phone/link', true).then(function (j) {
      say(''); linkUrl.value = j.url; linkBox.hidden = false; linkInfo.hidden = false; linkGo.textContent = linkGo.dataset.tAgain;
      linkUrl.focus(); linkUrl.select();
    }).catch(function (e) { say(e.message, false); }).then(function () { linkGo.disabled = false; });
  });
  copy.addEventListener('click', function () {
    var done = function () { copy.textContent = T('common.copied'); setTimeout(function () { copy.textContent = T('common.copy'); }, 2000); };
    if (navigator.clipboard && window.isSecureContext) { navigator.clipboard.writeText(linkUrl.value).then(done, function () { linkUrl.select(); }); }
    else { linkUrl.select(); try { if (document.execCommand('copy')) done(); } catch (e) { /* o link segue selecionado */ } }
  });

  // ---- celulares conectados (o admin vê e revoga os de todos) ----
  var admin = document.querySelector('.ph-card').getAttribute('data-admin') === '1';
  var list = document.getElementById('ph-list'), none = document.getElementById('ph-none');
  var base = admin ? '/admin/phone/devices' : '/phone/devices';
  function render(devs) {
    list.textContent = '';
    devs.forEach(function (d) {
      var li = document.createElement('li'); li.setAttribute('data-id', d.id);
      var n = document.createElement('span'); n.className = 'tv-name'; n.textContent = d.name + (admin && d.user ? ' · ' + d.user : '');
      var w = document.createElement('span'); w.className = 'tv-when'; w.textContent = T('ph.connected_at', {date: d.created}) + (d.seen && d.seen !== d.created ? ' · ' + T('dev.seen', {date: d.seen}) : '');
      var b = document.createElement('button'); b.type = 'button'; b.className = 'tv-rev'; b.textContent = T('common.revoke'); b.setAttribute('aria-label', T('dev.revoke_aria', {name: d.name}));
      li.appendChild(n); li.appendChild(w); li.appendChild(b); list.appendChild(li);
    });
    none.hidden = devs.length > 0;
  }
  function refresh() { return api(base).then(function (j) { render(j.devices || []); }).catch(function () { /* mantém a lista */ }); }
  list.addEventListener('click', function (e) {
    var b = e.target.closest('.tv-rev'); if (!b) return;
    var li = b.closest('li');
    sfConfirm(T('ph.revoke_q'), {title: T('dev.revoke_title'), ok: T('common.revoke'), danger: true}).then(function (ok) {
      if (!ok) return;
      b.disabled = true;
      api(base + '/' + li.getAttribute('data-id') + '/revoke', true).then(function () { li.remove(); none.hidden = list.children.length > 0; })
        .catch(function (err) { b.disabled = false; say(err.message, false); });
    });
  });
  refresh();
})();
