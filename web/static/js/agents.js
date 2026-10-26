// Página /admin/agents: chaves de API (TMDB, TVDB, OMDB, SubDL); o idioma dos agentes segue o do usuário (59.37). Lista + modal Editar/Remover (mesmo padrão de /admin/users).
(window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () {
  'use strict';
  var list = document.getElementById('ag-list');
  if (!list) return;
  var cnt = document.getElementById('ag-count'), NS = 'http://www.w3.org/2000/svg', data = null;

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
  function actBtn(tip, ic, fn, hidden) {
    var b = el('button'); b.type = 'button'; b.setAttribute('data-tip', tip); b.setAttribute('aria-label', tip);
    if (hidden) { b.className = 'um-ph'; b.disabled = true; b.tabIndex = -1; }
    b.appendChild(icon(ic));
    b.addEventListener('click', function (e) { e.stopPropagation(); fn(); });
    return b;
  }

  function render() {
    var n = data.agents.filter(function (a) { return a.set; }).length;
    cnt.textContent = T('ag.count', {n: n, total: data.agents.length});
    list.textContent = '';
    data.agents.forEach(function (a) {
      var row = el('div', 'lm-row'); row.tabIndex = 0;
      row.appendChild(icon('i-key'));
      var who = el('div', 'um-who'); who.appendChild(el('div', 'lm-name', a.name)); who.appendChild(el('div', 'um-user', a.desc));
      row.appendChild(who);
      var st = el('div', 'um-role ag-role', a.set ? T('ag.set', {masked: a.masked}) : T('ag.unset'));
      if (a.test) { st.appendChild(el('span', 'ag-res ag-' + a.test.state, a.test.state === 'busy' ? T('ag.busy') : a.test.state === 'ok' ? T('ag.ok') : a.test.state === 'invalid' ? T('ag.invalid') : T('ag.unknown'))); if (a.test.message && a.test.state !== 'busy') st.title = a.test.message; }
      row.appendChild(st);
      var acts = el('div', 'lm-acts');
      acts.appendChild(actBtn(T('ag.tip.test'), 'i-activity', function () { testSaved(a); }, !a.set));
      acts.appendChild(actBtn(a.set ? T('ag.tip.change') : T('ag.tip.add'), 'i-edit', function () { openEdit(a); }));
      acts.appendChild(actBtn(T('ag.tip.remove'), 'i-trash', function () { openDelete(a); }, !a.set));
      row.appendChild(acts);
      row.addEventListener('click', function () { openEdit(a); });
      row.addEventListener('keydown', function (e) { if (e.target === row && e.key === 'Enter') openEdit(a); });
      list.appendChild(row);
    });
  }
  function upsert(a) { var i = data.agents.findIndex(function (x) { return x.id === a.id; }); if (i >= 0) data.agents[i] = a; render(); }
  // testa a chave salva e mostra o resultado na linha
  function testSaved(a) {
    a.test = { state: 'busy' }; render();
    api('/admin/agents/' + a.id + '/test', {}).then(function (j) { a.test = j; })
      .catch(function (e) { a.test = { state: 'error', message: e.message }; }).then(function () { render(); });
  }

  // ---- modal Chave ----
  var ov = el('div', 'em-overlay'); ov.hidden = true;
  ov.innerHTML = '<div class="em-win em-small" role="dialog" aria-modal="true" aria-labelledby="ag-t">' +
    '<div class="em-head"><span id="ag-t"></span><button type="button" class="em-x" aria-label="' + T('common.close') + '">✕</button></div>' +
    '<div class="em-pane"><div class="um-f"><div class="em-lab" id="ag-l">' + T('ag.key') + '</div>' +
    '<input type="password" class="em-q" id="ag-k" autocomplete="off" autocapitalize="off" spellcheck="false"></div>' +
    '<p class="ld-text" id="ag-h"></p></div>' +
    '<div class="em-foot"><span class="em-err" id="ag-e"></span><button type="button" class="em-btn em-cancel" id="ag-c">' + T('common.cancel') + '</button>' +
    '<button type="button" class="em-btn em-cancel" id="ag-t2" disabled>' + T('sv.test') + '</button>' +
    '<button type="button" class="em-btn em-save" id="ag-s" disabled>' + T('common.save') + '</button></div></div>';
  document.body.appendChild(ov);
  var q = function (s) { return ov.querySelector(s); };
  var title = q('#ag-t'), ik = q('#ag-k'), help = q('#ag-h'), err = q('#ag-e'), sv = q('#ag-s'), tb = q('#ag-t2'), lab = q('#ag-l'), editing = null, busy = false, testing = false;

  function typed() { return ik.value.trim(); }
  function valid() { return /^\S{1,200}$/.test(typed()); }  // chave nova digitada e aceitável
  // a chave só muda se o usuário digitar uma nova; vazio = mantém a salva
  function check() {
    var bad = typed() !== '' && !valid();
    sv.disabled = busy || bad || !valid();
    tb.disabled = busy || testing || bad || !(valid() || (editing && editing.set));
  }
  function say(state, text) { err.textContent = text; err.className = 'em-err' + (state === 'ok' ? ' ag-ok' : ''); }
  function closeEdit() { if (busy) return; ov.hidden = true; editing = null; ik.value = ''; }
  function openEdit(a) {
    editing = a; say('', ''); ik.value = ''; testing = false;
    title.textContent = T('ag.key_title', {name: a.name});
    lab.textContent = T('ag.key');
    ik.placeholder = a.set ? a.masked : T('ag.ph');
    help.textContent = '';
    var link = el('a', null, T('ag.get', {name: a.name})); link.href = a.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
    help.appendChild(link);
    ov.hidden = false; check(); ik.focus();
  }
  ik.addEventListener('input', function () { say('', ''); check(); });
  tb.addEventListener('click', function () {
    if (busy || testing || !editing || tb.disabled) return;
    testing = true; check(); say('', T('common.testing'));
    var a = editing;
    api('/admin/agents/' + a.id + '/test', valid() ? { key: typed() } : {})  // sem chave digitada, testa a salva
      .then(function (j) { if (editing === a) say(j.state, (j.state === 'ok' ? '✓ ' : j.state === 'invalid' ? '✗ ' : '? ') + j.message); })
      .catch(function (e) { if (editing === a) say('error', e.message || T('ag.test_fail')); })
      .then(function () { testing = false; check(); });
  });
  ik.addEventListener('keydown', function (e) { if (e.key === 'Enter' && !sv.disabled) sv.click(); });
  q('.em-x').addEventListener('click', closeEdit);
  q('#ag-c').addEventListener('click', closeEdit);
  ov.addEventListener('mousedown', function (e) { if (e.target === ov) closeEdit(); });
  sv.addEventListener('click', function () {
    if (busy || !editing || sv.disabled) return;
    var body = { key: typed() }, newKey = true;  // o idioma não é daqui: segue o do usuário (59.37)
    busy = true; sv.disabled = true; tb.disabled = true; say('', '');
    api('/admin/agents/' + editing.id, body)
      .then(function (j) { busy = false; testing = false; ov.hidden = true; editing = null; ik.value = ''; upsert(j.agent); if (newKey) testSaved(data.agents.find(function (x) { return x.id === j.agent.id; })); })  // chave nova: já confere se o serviço aceita
      .catch(function (e) { busy = false; say('error', e.message || T('common.save_failed')); check(); });
  });

  // ---- modal Remover chave ----
  var dv = el('div', 'em-overlay'); dv.hidden = true;
  dv.innerHTML = '<div class="em-win em-small" role="dialog" aria-modal="true" aria-labelledby="agd-t">' +
    '<div class="em-head"><span id="agd-t">' + T('ag.del.title') + '</span><button type="button" class="em-x" aria-label="' + T('common.close') + '">✕</button></div>' +
    '<div class="em-pane"><p class="ld-text"></p></div>' +
    '<div class="em-foot"><span class="em-err" id="agd-e"></span><button type="button" class="em-btn em-cancel" id="agd-c">' + T('common.cancel') + '</button>' +
    '<button type="button" class="em-btn em-danger" id="agd-x">' + T('common.remove') + '</button></div></div>';
  document.body.appendChild(dv);
  var dtxt = dv.querySelector('.ld-text'), derr = dv.querySelector('#agd-e'), dx = dv.querySelector('#agd-x'), da = null, dbusy = false;

  function closeDel() { if (dbusy) return; dv.hidden = true; da = null; }
  function openDelete(a) {
    da = a; derr.textContent = ''; dx.disabled = false;
    dtxt.textContent = T('ag.del.text', {name: a.name});
    dv.hidden = false;
  }
  dv.querySelector('.em-x').addEventListener('click', closeDel);
  dv.querySelector('#agd-c').addEventListener('click', closeDel);
  dv.addEventListener('mousedown', function (e) { if (e.target === dv) closeDel(); });
  dx.addEventListener('click', function () {
    if (!da || dbusy) return;
    dbusy = true; dx.disabled = true; derr.textContent = '';
    api('/admin/agents/' + da.id + '/delete', {}).then(function (j) { dbusy = false; dv.hidden = true; da = null; upsert(j.agent); })
      .catch(function (e) { dbusy = false; dx.disabled = false; derr.textContent = e.message || T('common.remove_failed'); });
  });

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    if (!dv.hidden) closeDel(); else if (!ov.hidden) closeEdit();
  });

  api('/admin/agents/data').then(function (j) { data = j; render(); })
    .catch(function () { list.textContent = ''; list.appendChild(el('p', 'la-empty', T('ag.load_fail'))); });
});
