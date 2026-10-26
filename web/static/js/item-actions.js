// Ações admin do menu "⋯" (23.25): {act: 'analyze'|'history'|'refresh'|'match'|'unmatch'|'delete'|'addcol'|'examine', kind, ref, name}.
(window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () {
  var el = document.createElement('div'); el.className = 'em-overlay'; el.hidden = true;
  el.innerHTML = '<div class="em-win em-small"><div class="em-head"><span id="ia-t"></span><button type="button" class="em-x"></button></div>' +
    '<div class="em-pane" id="ia-b"></div><div class="em-foot" id="ia-f"></div></div>';
  document.body.appendChild(el);
  var W = el.firstChild, TT = el.querySelector('#ia-t'), B = el.querySelector('#ia-b'), F = el.querySelector('#ia-f');
  function close() { el.hidden = true; }
  el.querySelector('.em-x').textContent = '✕'; el.querySelector('.em-x').setAttribute('aria-label', T('common.close'));
  el.querySelector('.em-x').addEventListener('click', close);
  el.addEventListener('mousedown', function (e) { if (e.target === el) close(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !el.hidden) { e.stopImmediatePropagation(); close(); } }, true);
  function dlg(title, body, buttons) {
    W.className = 'em-win em-small'; TT.textContent = title; B.innerHTML = ''; F.innerHTML = '';
    if (typeof body === 'string') B.textContent = body; else B.appendChild(body);
    (buttons || []).forEach(function (b) {
      var x = document.createElement('button'); x.type = 'button'; x.className = 'em-btn ' + (b.cls || 'em-cancel'); x.textContent = b.l;
      x.addEventListener('click', b.fn); F.appendChild(x);
    });
    el.hidden = false;
  }
  var CLOSE = {l: T('common.close'), fn: close};
  var CANCEL = {l: T('common.cancel'), fn: close};
  function url(it, tail) { return '/admin/item/' + it.kind + '/' + encodeURIComponent(it.ref) + '/' + tail; }
  async function post(u, fd) {
    var r = await fetch(u, {method: 'POST', body: fd}), j = {};
    try { j = await r.json(); } catch (e) {}
    if (r.status === 401) { location.href = '/login'; }
    return {ok: r.ok, j: j};
  }
  function fmt(s) { return SF_I18N.fmt.clockH(s); }

  var A = {
    analyze: async function (it) {
      dlg(T('lib.analyze'), T('ia.analyzing'), []);
      var r = await post(url(it, 'analyze'));
      dlg(T('lib.analyze'), r.ok ? T('ia.analyzed', {n: r.j.analyzed, total: r.j.total}) : (SF_I18N.msg(r.j) || T('common.error')), [CLOSE]);
    },
    refresh: async function (it) {
      // 35.19: sem modal — a capa gira (grade e página do item) e atualiza sozinha, igual ao Corrigir Correspondência
      var r = await post(url(it, 'refresh'));
      if (r.ok) { if (window.sfScanKick) window.sfScanKick(it.ref); else location.reload(); }
      else dlg(T('lib.refresh_all'), SF_I18N.msg(r.j) || T('common.error'), [CLOSE]);
    },
    examine: async function (it) {
      // 46.4: Examinar arquivos só deste filme/série; segue em segundo plano (a capa gira e a página recarrega ao terminar)
      var r = await post(url(it, 'examine'));
      if (r.ok) { if (window.sfScanKick) window.sfScanKick(it.ref); }
      else dlg(T('pn.scan_one'), SF_I18N.msg(r.j) || T('common.error'), [CLOSE]);
    },
    trickplay: async function (it) {
      // 49.2: Gerar miniaturas só deste filme/série; segue em segundo plano (a capa gira e a página recarrega ao terminar)
      var r = await post(url(it, 'trickplay'));
      if (r.ok) { if (window.sfScanKick) window.sfScanKick(it.ref); }
      else dlg(T('lib.gen_thumbs'), SF_I18N.msg(r.j) || T('common.error'), [CLOSE]);
    },
    optimize: async function (it) {
      // 52.10: entra na fila na hora (fora da janela de horário); a conversão roda em segundo plano
      var r = await post(url(it, 'optimize')), n = r.j.queued || 0;
      dlg(T('ia.optimize'), r.ok ? (n ? Tn('ia.queued', n) : T('ia.nothing')) : (SF_I18N.msg(r.j) || T('common.error')), [CLOSE]);
    },
    unoptimize: async function (it) {
      var r = await post(url(it, 'optimize/remove')), n = r.j.removed || 0;
      dlg(T('im.unoptimize'), r.ok ? (n ? Tn('ia.removed', n) : T('ia.none_opt')) : (SF_I18N.msg(r.j) || T('common.error')), [CLOSE]);
    },
    history: async function (it) {
      dlg(T('ia.history'), T('common.loading'), []);
      var r = await fetch(url(it, 'history')), j = await r.json(), box = document.createElement('div');
      if (!j.items.length) box.textContent = T('ia.nohist');
      j.items.forEach(function (x) {
        var d = document.createElement('div'); d.className = 'em-file';
        d.innerHTML = '<div class="em-path"></div><div class="em-meta"></div>';
        d.firstChild.textContent = x.profile + (x.episode ? ' · ' + x.episode : '');
        d.lastChild.textContent = (x.watched ? T('ia.watched') : T('ia.stopped', {pos: fmt(x.position)})) + ' · ' + (x.at || '');
        box.appendChild(d);
      });
      dlg(T('ia.history'), box, [CLOSE]);
    },
    unmatch: function (it) {
      dlg(T('ia.unmatch_title'), T('ia.unmatch_text', {name: it.name || T('ia.item')}), [
        CANCEL,
        {l: T('common.remove'), cls: 'em-save', fn: async function () {
          var r = await post(url(it, 'unmatch'));
          if (r.ok) location.reload(); else dlg(T('ia.unmatch_title'), SF_I18N.msg(r.j) || T('common.error'), [CLOSE]);
        }}]);
    },
    delete: function (it) {
      dlg(T('lib.delete'), T('ia.delete_text', {name: it.name || T('ia.item')}), [
        CANCEL,
        {l: T('lib.delete'), cls: 'em-save', fn: async function () {
          var r = await post(url(it, 'delete'));
          if (r.ok) location.href = r.j.next; else dlg(T('lib.delete'), SF_I18N.msg(r.j) || T('common.error'), [CLOSE]);
        }}]);
    },
    'bulk-delete': function (it) {
      var n = it.ids.length;
      dlg(T('lib.delete'), Tn('ia.bulk_text', n), [
        CANCEL,
        {l: T('lib.delete'), cls: 'em-save', fn: async function () {
          var r = await fetch('/bulk/delete', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ids: it.ids})}), j = {};
          try { j = await r.json(); } catch (e) {}
          if (r.status === 401) { location.href = '/login'; return; }
          if (r.ok) location.reload(); else dlg(T('lib.delete'), SF_I18N.msg(j) || T('common.error'), [CLOSE]);
        }}]);
    },
    delcol: function (it) {
      dlg(T('ia.delcol_title'), T('ia.delcol_text', {name: it.name || ''}), [
        CANCEL,
        {l: T('lib.delete'), cls: 'em-save', fn: async function () {
          var r = await fetch('/admin/collections/' + encodeURIComponent(it.ref), {method: 'DELETE'}), j = {};
          try { j = await r.json(); } catch (e) {}
          if (r.status === 401) { location.href = '/login'; return; }
          if (r.ok) location.href = it.next || '/'; else dlg(T('ia.delcol_title'), SF_I18N.msg(j) || T('common.error'), [CLOSE]);
        }}]);
    },
    match: async function (it) {
      // Corrigir Correspondência (25.5, captura 56): Local, abas Opções de busca / Auto Corresponder, resultados com sinopse e pôster
      var kind = it.kind === 'movie' ? 'movie' : 'tv', box = document.createElement('div'), chosen = null, info = {};
      box.className = 'cm-box';
      box.innerHTML = '<div class="cm-top"><div class="cm-local"></div><div class="cm-tabs"><button type="button" class="on" data-t="opt">' + T('ia.opt_tab') + '</button>' +
        '<button type="button" data-t="auto">' + T('ia.auto_tab') + '</button></div></div>' +
        '<div class="cm-fields"><label>' + T('lib.col.title') + '<input type="text" class="em-q cm-t"></label><label class="cm-y">' + T('lib.col.year') + '<input type="text" inputmode="numeric" maxlength="4" class="em-q cm-yr"></label>' +
        '<button type="button" class="em-btn em-save cm-go">' + T('nav.search') + '</button></div><div class="cm-res"></div>';
      var local = box.querySelector('.cm-local'), tabs = box.querySelectorAll('.cm-tabs button'), fields = box.querySelector('.cm-fields'),
          qt = box.querySelector('.cm-t'), qy = box.querySelector('.cm-yr'), res = box.querySelector('.cm-res');
      qt.value = it.name || ''; local.textContent = T('ia.local', {path: '…'});
      dlg(T('ia.match_title'), box, [CANCEL, {l: T('ia.search'), cls: 'em-save', fn: apply}]);
      W.className = 'em-win em-wide';
      var OK = F.lastChild; OK.disabled = true;
      function mid(s) { return s.length > 60 ? s.slice(0, 28) + '…' + s.slice(-28) : s; }
      async function apply() {
        if (!chosen) return;
        OK.disabled = true;
        var fd = new FormData(); fd.append('tmdb_id', chosen);
        var r2 = await post('/admin/media/' + it.ref + '/match', fd);
        if (r2.ok) { close(); if (window.sfScanKick) window.sfScanKick(it.ref); else location.reload(); }  // 35.16: fecha e a capa gira até terminar
        else { OK.disabled = false; res.textContent = SF_I18N.msg(r2.j) || T('common.error'); }
      }
      async function go() {
        chosen = null; OK.disabled = true; res.textContent = T('ia.searching');
        var u = '/admin/tmdb-search?type=' + kind + '&q=' + encodeURIComponent(qt.value) + '&year=' + encodeURIComponent(qy.value), j = {};
        try { var r = await fetch(u); if (r.status === 401) { location.href = '/login'; return; } j = await r.json(); } catch (e) { res.textContent = T('common.network_error'); return; }
        res.innerHTML = '';
        if (j.error) { res.textContent = SF_I18N.msg(j); return; }
        if (!j.results.length) { res.textContent = T('ia.not_found'); return; }
        j.results.forEach(function (x) {
          var d = document.createElement('div'); d.className = 'cm-item';
          d.innerHTML = '<div class="cm-main"><div class="cm-row"><b></b><span></span></div><p></p></div>' + (x.poster ? '<img alt="" loading="lazy">' : '');
          d.querySelector('b').textContent = x.title; d.querySelector('span').textContent = x.year || '';
          d.querySelector('p').textContent = x.overview || '';
          if (x.poster) d.querySelector('img').src = x.poster;
          d.addEventListener('click', function () {
            res.querySelectorAll('.cm-item.on').forEach(function (n) { n.classList.remove('on'); });
            d.classList.add('on'); chosen = x.id; OK.disabled = false;
          });
          res.appendChild(d);
        });
      }
      function tab(t) {
        tabs.forEach(function (b) { b.classList.toggle('on', b.dataset.t === t); });
        fields.hidden = t !== 'opt';
        if (t === 'auto') { qt.value = (info.auto && info.auto.title) || qt.value; qy.value = (info.auto && info.auto.year) || ''; go(); }
      }
      tabs.forEach(function (b) { b.addEventListener('click', function () { tab(b.dataset.t); }); });
      box.querySelector('.cm-go').addEventListener('click', go);
      [qt, qy].forEach(function (i) { i.addEventListener('keydown', function (e) { if (e.key === 'Enter') go(); }); });
      try {
        var ri = await fetch('/admin/media/' + it.ref + '/match-info');
        if (ri.status === 401) { location.href = '/login'; return; }
        if (ri.ok) { info = await ri.json(); local.textContent = T('ia.local', {path: mid(info.path || '—')}); local.title = info.path || ''; qt.value = info.title || qt.value; qy.value = info.year || ''; }
      } catch (e) {}
      qt.focus(); go();
    }
  };
  // Adicionar à coleção… (25.2): descobre a biblioteca do item e abre o modal de 24.5 com o item como seleção
  A.addcol = async function (it) {
    try {
      var r = await fetch('/admin/item/' + it.kind + '/' + it.ref + '/edit');
      if (r.status === 401) { location.href = '/login'; return; }
      var j = await r.json();
      if (!r.ok || !j.library_id) { dlg(T('ia.addcol_title'), T('ia.open_fail'), [CLOSE]); return; }
      if (window.sfAddToCollection) window.sfAddToCollection([parseInt(it.ref, 10)], it.kind, j.library_id, it.name);
    } catch (e) { dlg(T('ia.addcol_title'), T('common.network_error'), [CLOSE]); }
  };
  // Conceder Acesso a <título> (25.6, captura 57): acesso é por biblioteca; só usuários locais
  A.access = async function (it) {
    var box = document.createElement('div'), data = null;
    box.className = 'ac-box';
    box.innerHTML = '<p class="ac-txt"></p><input type="text" class="ac-in" list="ac-dl" placeholder="' + T('la.m.ph') + '" autocomplete="off" autocapitalize="off" spellcheck="false">' +
      '<datalist id="ac-dl"></datalist><div class="ac-msg"></div><div class="ac-h">' + T('la.accounts') + '</div><div class="ac-list"></div>';
    var txt = box.querySelector('.ac-txt'), inp = box.querySelector('.ac-in'), dl = box.querySelector('#ac-dl'),
        msg = box.querySelector('.ac-msg'), list = box.querySelector('.ac-list');
    function paint() {
      txt.textContent = T('ia.access_txt', {title: data.title, lib: data.library});
      dl.innerHTML = ''; list.innerHTML = '';
      data.others.forEach(function (u) { var o = document.createElement('option'); o.value = u.username; dl.appendChild(o); });
      data.with_access.forEach(function (u) {
        var d = document.createElement('div'); d.className = 'ac-user';
        d.innerHTML = '<span class="ac-av"></span><span class="ac-n"></span>';
        d.firstChild.textContent = (u.username || '?').charAt(0).toUpperCase();
        d.lastChild.textContent = u.username + (u.admin ? T('ia.admin_suffix') : '');
        list.appendChild(d);
      });
    }
    async function send() {
      var v = inp.value.trim(); if (!v) return;
      msg.textContent = T('common.sending'); msg.className = 'ac-msg';
      var fd = new FormData(); fd.append('user', v);
      var r = await post(url(it, 'access'), fd);
      if (!r.ok) { msg.textContent = SF_I18N.msg(r.j) || T('common.error'); msg.className = 'ac-msg err'; return; }
      data = r.j; inp.value = ''; msg.textContent = T('ia.granted', {name: v}); paint();
    }
    dlg(T('ia.access_title', {name: it.name || ''}), T('common.loading'), [CANCEL, {l: T('ia.send'), cls: 'em-save', fn: send}]);
    var r = await fetch(url(it, 'access'));
    if (r.status === 401) { location.href = '/login'; return; }
    if (!r.ok) { dlg(T('ia.access_short'), T('ia.open_fail'), [CLOSE]); return; }
    data = await r.json(); B.innerHTML = ''; B.appendChild(box); W.className = 'em-win em-access'; paint(); inp.focus();
    inp.addEventListener('keydown', function (e) { if (e.key === 'Enter') send(); });
  };
  window.sfItemAction = function (it) { if (A[it.act]) A[it.act](it); };
});
