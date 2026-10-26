// Modal "Garantir acesso à biblioteca" (27.3, capturas 77–79): window.sfLibAccess.open(usuário|null, dados)
// Passo 1: pesquisar e escolher o usuário (a lista só aparece depois de digitar); passo 2: marcar as bibliotecas. Com usuário já informado abre direto no passo 2.
// 3º argumento {lib: id} (29.7, menu ⋮ da biblioteca): textos da captura 92 e a biblioteca já marcada no passo 2.
(window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () {
  'use strict';
  var el = document.createElement('div'); el.className = 'em-overlay'; el.hidden = true;
  el.innerHTML = '<div class="em-win la-win" role="dialog" aria-modal="true" aria-labelledby="la-ttl">' +
    '<div class="em-head"><span id="la-ttl">' + T('la.grant') + '</span><button type="button" class="em-x" aria-label="' + T('common.close') + '">✕</button></div>' +
    '<div class="em-pane la-pane"></div>' +
    '<div class="em-foot la-foot"><button type="button" class="em-btn em-cancel la-cancel">' + T('common.cancel') + '</button><span class="em-err"></span>' +
    '<button type="button" class="em-btn em-cancel la-prev">' + T('common.prev') + '</button><button type="button" class="em-btn em-save la-next">' + T('common.continue') + '</button></div></div>';
  document.body.appendChild(el);
  var P = el.querySelector('.la-pane'), ERR = el.querySelector('.em-err'), PREV = el.querySelector('.la-prev'),
      NEXT = el.querySelector('.la-next'), data = null, user = null, step = 1, direct = false, sel = [], init = '', busy = false, opt = null;

  function mk(t, c, x) { var e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; }
  function fold(s) { return (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase(); }
  function name(u) { return u.full_name || u.username; }
  function key(a) { return a.slice().sort(function (x, y) { return x - y; }).join(','); }
  function dirty() { return step === 2 && key(sel) !== init; }
  function close(force) {
    if (!force && dirty()) { sfConfirm(T('common.discard_text'), {title: T('common.discard_title'), ok: T('common.close'), danger: true}).then(function (ok) { if (ok) close(true); }); return; }
    el.hidden = true; document.documentElement.classList.remove('em-open'); P.textContent = ''; user = null; busy = false;
  }

  function step1() {
    step = 1; ERR.textContent = ''; P.textContent = '';
    PREV.hidden = true; NEXT.textContent = T('common.continue'); NEXT.disabled = !user;
    P.appendChild(mk('p', 'la-txt', opt ? T('la.m.txt_lib') : T('la.m.txt')));
    var q = mk('input', 'la-q'); q.type = 'text'; q.placeholder = opt ? T('la.m.ph_lib') : T('la.m.ph'); q.autocomplete = 'off';
    q.setAttribute('autocapitalize', 'off'); q.setAttribute('autocorrect', 'off'); q.spellcheck = false;
    var head = mk('div', 'la-rh', opt ? T('la.m.friends') : T('la.m.results')), list = mk('div', 'la-ul');
    P.appendChild(q); P.appendChild(head); P.appendChild(list);
    function draw() {
      var t = fold(q.value.trim()); list.textContent = '';
      head.hidden = !t;
      if (!t) { user = null; NEXT.disabled = true; return; }  // sem busca: nada na lista, nem o cabeçalho
      var rows = data.users.filter(function (u) { return fold(u.username + ' ' + (u.full_name || '')).indexOf(t) >= 0; });
      if (user && !rows.some(function (u) { return u.id === user.id; })) { user = null; NEXT.disabled = true; }
      if (!rows.length) { list.appendChild(mk('p', 'la-none', T('la.m.nouser'))); return; }
      rows.forEach(function (u) {
        var b = mk('button', 'la-ur' + (user && user.id === u.id ? ' on' : '')); b.type = 'button';
        var img = mk('img', 'la-uav'); img.src = '/avatar/' + u.id; img.alt = '';
        b.appendChild(img); b.appendChild(mk('span', 'la-un', name(u)));
        if (u.full_name) b.appendChild(mk('span', 'la-uu', (opt ? '• ' : '') + u.username));
        b.appendChild(mk('span', 'la-ck', '✓'));
        b.addEventListener('click', function () { user = u; NEXT.disabled = false; draw(); });
        list.appendChild(b);
      });
    }
    q.addEventListener('input', draw);
    q.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); if (user) step2(); } });
    draw(); q.focus();
  }

  function step2() {
    step = 2; ERR.textContent = ''; P.textContent = '';
    sel = user.libraries.slice(); init = key(sel);
    if (opt && opt.lib && sel.indexOf(opt.lib) < 0) sel.push(opt.lib);  // esta biblioteca já vem marcada (29.7)
    PREV.hidden = direct; NEXT.textContent = T('common.save'); NEXT.disabled = false;
    P.appendChild(mk('p', 'la-txt', T('la.m.choose', {name: name(user)})));
    if (!data.libraries.length) { P.appendChild(mk('p', 'la-none', T('la.m.nolibs'))); return; }
    var box = mk('div', 'la-tree'); P.appendChild(box);
    function allSel() { return sel.length === data.libraries.length; }
    // Servidor inteiro marcado: uma só linha "<servidor> (Todas as Bibliotecas)"; senão, árvore com as bibliotecas
    // (checkbox do servidor desmarcado quando a seleção é parcial). Marcar todas, uma a uma, também recolhe.
    function draw() {
      box.textContent = '';
      if (allSel()) {
        var one = mk('label', 'la-srvl la-one'), cb1 = mk('input'); cb1.type = 'checkbox'; cb1.checked = true;
        one.appendChild(cb1); one.appendChild(mk('span', null, T('la.m.all', {server: data.server})));
        cb1.addEventListener('change', function () { sel = []; draw(); });
        box.appendChild(one); return;
      }
      var srv = mk('div', 'la-srv'), tg = mk('button', 'la-tg', '▲'), kids = mk('div', 'la-kids');
      tg.type = 'button'; tg.setAttribute('aria-label', T('la.m.toggle')); tg.setAttribute('aria-expanded', 'true');
      var all = mk('input'); all.type = 'checkbox'; all.checked = false;
      var lb = mk('label', 'la-srvl'); lb.appendChild(all); lb.appendChild(mk('span', null, data.server));
      srv.appendChild(tg); srv.appendChild(lb); box.appendChild(srv); box.appendChild(kids);
      data.libraries.forEach(function (l) {
        var row = mk('label', 'la-lib'), cb = mk('input'); cb.type = 'checkbox'; cb.checked = sel.indexOf(l.id) >= 0;
        row.appendChild(cb); row.appendChild(mk('span', null, l.name)); kids.appendChild(row);
        cb.addEventListener('change', function () {
          sel = sel.filter(function (i) { return i !== l.id; }); if (cb.checked) sel.push(l.id);
          if (allSel()) draw();
        });
      });
      all.addEventListener('change', function () { sel = data.libraries.map(function (l) { return l.id; }); draw(); });
      tg.addEventListener('click', function () {
        var open = kids.hidden; kids.hidden = !open; tg.textContent = open ? '▲' : '▼'; tg.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
    }
    draw();
  }

  async function save() {
    if (busy) return; busy = true; NEXT.disabled = true; ERR.textContent = '';
    try {
      var r = await fetch('/admin/access/user/' + user.id, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({libraries: sel})}), j = {};
      try { j = await r.json(); } catch (e) {}
      if (r.status === 401) { location.href = '/login'; return; }
      if (!r.ok) { ERR.textContent = SF_I18N.msg(j) || T('common.save_failed'); busy = false; NEXT.disabled = false; return; }
      document.dispatchEvent(new CustomEvent('la:saved', {detail: j.user}));
      close(true);
    } catch (e) { ERR.textContent = T('common.network_error'); busy = false; NEXT.disabled = false; }
  }

  NEXT.addEventListener('click', function () { if (step === 1) { if (user) step2(); } else save(); });
  PREV.addEventListener('click', function () {
    if (step === 2 && dirty()) { sfConfirm(T('la.m.back_q'), {title: T('common.discard_title'), ok: T('common.back'), danger: true}).then(function (ok) { if (ok) step1(); }); return; }
    step1();
  });
  el.querySelector('.la-cancel').addEventListener('click', function () { close(false); });
  el.querySelector('.em-x').addEventListener('click', function () { close(false); });
  el.addEventListener('mousedown', function (e) { if (e.target === el) close(false); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !el.hidden) { e.stopImmediatePropagation(); close(false); } }, true);

  window.sfLibAccess = {
    open: function (u, d, o) {
      data = d; opt = o || null; user = u || null; direct = !!u; busy = false;
      el.hidden = false; document.documentElement.classList.add('em-open');
      if (direct) step2(); else step1();
    }
  };
});
