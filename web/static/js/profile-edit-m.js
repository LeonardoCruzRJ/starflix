// Editar perfil no celular (≤700px): telas trocadas por #hash (a seta e o voltar do aparelho funcionam), sem recarregar a página.
// Campos: POST /account/profile; idioma: /account/settings; senha: /account/password; foto: abre o editor de corte (avatar-editor.js).
(window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () {  // 59.15: textos montados aqui precisam do catálogo
  'use strict';
  var root = document.getElementById('pem'); if (!root) return;
  function el(t, c, x) { var e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; }
  var screens = {}, fields = {}, cur = {};
  root.querySelectorAll('.pem-s').forEach(function (s) { screens[s.dataset.s] = s; });
  var sheet = document.getElementById('pem-sheet'), dlg = document.getElementById('pem-dlg');

  function post(url, body) {
    return fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)})
      .then(function (r) { if (r.status === 401) { location.href = '/login'; throw 0; } return r.json().then(function (j) { return [r, j]; }); });
  }
  function goBack() { if (history.length > 1 && location.hash) history.back(); else location.hash = ''; }

  // ---- texto das linhas da tela principal e da Conta
  function paint(field, v) {
    root.querySelectorAll('[data-v="' + field + '"]').forEach(function (sp) {
      var t = field === 'show_badge' ? (v === '1' ? sp.dataset.tOn : sp.dataset.tOff) : String(v || '').replace(/\s*\n\s*/g, ' ');
      sp.classList.toggle('pem-ph', !t);
      sp.textContent = t || sp.dataset.empty || '';
    });
  }
  root.querySelectorAll('[data-v]').forEach(function (sp) {
    var f = sp.dataset.v; if (f === 'lang') return;
    var v = f === 'show_badge' ? (root.querySelector('.pem-s[data-field="show_badge"]').dataset.value === '1' ? '1' : '0') : sp.textContent.trim();
    cur[f] = v; paint(f, v);
  });

  // ---- telas de um campo
  root.querySelectorAll('.pem-s[data-field]').forEach(function (sec) {
    var f = sec.dataset.field, type = sec.dataset.type || 'text', max = +sec.dataset.max || 0, input;
    var bar = el('header', 'pem-bar'), back = el('a', 'pem-back'); back.href = '#'; back.setAttribute('data-back', 'sub'); back.setAttribute('aria-label', T('common.back'));
    back.innerHTML = '<svg class="ic"><use href="#i-arrow-left"/></svg>'; bar.appendChild(back); bar.appendChild(el('h1', null, sec.dataset.title)); sec.appendChild(bar);
    var count = null, err = el('p', 'pem-err'), save = el('button', 'pem-save', T('common.save')); save.type = 'button'; save.disabled = true;
    if (type === 'check') {
      var lb = el('label', 'pem-check'); lb.appendChild(el('span', null, sec.dataset.label));
      input = el('input'); input.type = 'checkbox'; lb.appendChild(input); sec.appendChild(lb);
    } else {
      if (sec.dataset.help) sec.appendChild(el('p', 'pem-help', sec.dataset.help));
      input = el(type === 'area' ? 'textarea' : 'input', 'pem-input');
      if (type === 'area') input.rows = 3; else input.type = 'text';
      input.maxLength = max; input.autocomplete = 'off'; input.placeholder = sec.dataset.ph || '';
      if (sec.dataset.nocap) { input.setAttribute('autocapitalize', 'off'); input.setAttribute('autocorrect', 'off'); input.spellcheck = false; }
      sec.appendChild(input);
      if (!sec.dataset.nocount) { count = el('div', 'pem-count'); sec.appendChild(count); }
    }
    var foot = el('div', 'pem-foot'); foot.appendChild(err); foot.appendChild(save); sec.appendChild(foot);
    function val() { return type === 'check' ? (input.checked ? '1' : '0') : input.value.trim(); }
    function sync() { if (count) count.textContent = input.value.length + ' / ' + max; save.disabled = val() === String(cur[f] == null ? '' : cur[f]).trim(); }
    function reset() {
      var v = cur[f] == null ? '' : cur[f];
      if (type === 'check') input.checked = v === '1'; else input.value = v;
      err.textContent = ''; sync();
    }
    input.addEventListener(type === 'check' ? 'change' : 'input', sync);
    input.addEventListener('keydown', function (e) { if (e.key === 'Enter' && type !== 'area' && !save.disabled) save.click(); });
    save.addEventListener('click', function () {
      save.disabled = true; err.textContent = '';
      post(sec.dataset.url || '/account/profile', {field: f, value: type === 'check' ? val() === '1' : val()}).then(function (a) {
        if (!a[0].ok) { err.textContent = SF_I18N.msg(a[1]) || T('common.save_failed'); save.disabled = false; return; }
        var nv = type === 'check' ? val() : (a[1].value || '');
        cur[f] = nv; paint(f, nv); goBack();
      }).catch(function (e) { if (e !== 0) { err.textContent = T('common.conn_failed'); save.disabled = false; } });
    });
    fields[sec.dataset.s] = reset;
    cur[f] = type === 'check' ? (sec.dataset.value === '1' ? '1' : '0') : (sec.dataset.value || '');
  });

  // ---- idioma
  var ls = document.getElementById('pem-lang'), lsave = document.getElementById('pem-lang-save'), lerr = screens.idioma.querySelector('.pem-err');
  fields.idioma = function () { ls.value = root.dataset.lang; lsave.disabled = true; lerr.textContent = ''; };
  ls.addEventListener('change', function () { lsave.disabled = ls.value === root.dataset.lang; });
  lsave.addEventListener('click', function () {
    lsave.disabled = true; lerr.textContent = '';
    window.SF_I18N.set(ls.value).then(function (r) { return [r, r]; }).then(function (a) { if (a[0].status === 401) { location.href = '/login'; throw 0; } return a; }).then(function (a) {
      if (!a[0].ok) { lerr.textContent = SF_I18N.msg(a[1]) || T('common.save_failed'); lsave.disabled = false; return; }
      root.dataset.lang = ls.value; root.querySelector('[data-v="lang"]').textContent = ls.options[ls.selectedIndex].text; lsave.disabled = true;  // 59.6: SF_I18N.set já aplicou o idioma (ou recarregou)
    }).catch(function (e) { if (e !== 0) { lerr.textContent = T('common.conn_failed'); lsave.disabled = false; } });
  });

  // ---- senha
  var pn = document.getElementById('pem-pw-new'), pc = document.getElementById('pem-pw-conf'), pu = document.getElementById('pem-pw-cur'),
      po = document.getElementById('pem-pw-out'), ps = document.getElementById('pem-pw-save'), pe = screens.senha.querySelector('.pem-err');
  function pwCheck() { ps.disabled = !(pn.value && pc.value && pu.value); }
  fields.senha = function () { pn.value = pc.value = pu.value = ''; po.checked = false; pe.textContent = ''; pwCheck(); };
  [pn, pc, pu].forEach(function (i) { i.addEventListener('input', pwCheck); i.addEventListener('keydown', function (e) { if (e.key === 'Enter' && !ps.disabled) ps.click(); }); });
  ps.addEventListener('click', function () {
    ps.disabled = true; pe.textContent = '';
    post('/account/password', {new: pn.value, confirm: pc.value, current: pu.value, logout_others: po.checked}).then(function (a) {
      if (!a[0].ok) { pe.textContent = SF_I18N.msg(a[1]) || T('common.save_failed'); pwCheck(); return; }
      fields.senha(); goBack();
    }).catch(function (e) { if (e !== 0) { pe.textContent = T('common.conn_failed'); pwCheck(); } });
  });

  // ---- navegação
  function route() {
    var h = location.hash.slice(1), name = h;
    if (h === 'foto' || h === 'sair' || !screens[h]) name = h === 'sair' ? 'conta' : '';
    Object.keys(screens).forEach(function (k) { screens[k].hidden = k !== name; });
    if (fields[name]) fields[name]();
    sheet.hidden = h !== 'foto'; dlg.hidden = h !== 'sair';
    window.scrollTo(0, 0);
  }
  window.addEventListener('hashchange', route);
  root.addEventListener('click', function (e) {
    var b = e.target.closest('.pem-back');
    if (b) {
      e.preventDefault();
      if (b.dataset.back === 'main') { if (history.length > 1 && document.referrer) history.back(); else location.href = b.getAttribute('href'); }
      else goBack();
      return;
    }
    if (e.target.closest('[data-no]') || e.target === dlg || e.target === sheet) { goBack(); return; }
  });
  document.getElementById('pem-photo-btn').addEventListener('click', function () { location.hash = 'foto'; });
  document.getElementById('pem-dlg-ok').addEventListener('click', function () { location.href = '/logout'; });

  // ---- foto: Tirar Foto / Escolher da Biblioteca -> editor de corte
  var cam = document.getElementById('pem-file-cam'), lib = document.getElementById('pem-file-lib');
  sheet.querySelectorAll('[data-pick]').forEach(function (b) { b.addEventListener('click', function () { (b.dataset.pick === 'cam' ? cam : lib).click(); }); });
  [cam, lib].forEach(function (inp) {
    inp.addEventListener('change', function () {
      var f = inp.files && inp.files[0]; inp.value = ''; if (!f) return;
      history.replaceState(null, '', location.pathname + location.search); route();  // fecha o menu sem deixar #foto no histórico
      if (window.sfAvatarEditor) sfAvatarEditor.open(null, null, f, {url: root.dataset.avurl});
    });
  });
  route();
});
