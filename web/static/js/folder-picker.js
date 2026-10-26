// Navegador de pastas "Adicionar pasta" (28.11, capturas 84 e 85). window.sfFolderPicker.open({ folders, libraryId }, cb(path)).
(window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  var ov, win, st, cb, opts;

  function el(t, c, x) { var e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; }
  function icon(id, c) { var s = document.createElementNS(NS, 'svg'); s.setAttribute('class', 'ic ' + (c || '')); var u = document.createElementNS(NS, 'use'); u.setAttribute('href', '#' + id); s.appendChild(u); return s; }
  function close() { ov.remove(); ov = null; document.removeEventListener('keydown', onKey, true); }
  function onKey(e) { if (e.key === 'Escape') { e.stopImmediatePropagation(); close(); } }
  function join(a, b) { return (a === '/' ? '' : a) + '/' + b; }

  function load(path) {
    fetch('/admin/browse?path=' + encodeURIComponent(path), { headers: { Accept: 'application/json' } }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json();
    }).then(function (j) {
      if (!j) return;
      if (st.first) { st.first = false; st.typed = j.home.path; return load(j.home.path); }
      var miss = j.missing; st.data = j; st.path = miss ? st.typed : j.path; st.err = miss ? T('fp.not_found') : '';
      draw();
    }).catch(function () { st.err = T('fp.list_fail'); draw(); });
  }

  function side(d, col) {
    var list = [{ name: d.home.name, path: d.home.path, ic: 'i-home' }].concat(d.roots.map(function (r) { return { name: r.name, path: r.path, ic: 'i-folder' }; }));
    list.forEach(function (it) {
      var b = el('button', 'fp-item' + (st.path === it.path ? ' on' : '')); b.type = 'button';
      b.appendChild(icon(it.ic, 'ic-sm')); b.appendChild(el('span', '', it.name));
      b.addEventListener('click', function () { st.typed = it.path; load(it.path); });
      col.appendChild(b);
    });
  }

  function main(d, col) {
    if (d.parent != null) {
      var b = el('button', 'fp-item'); b.type = 'button'; b.appendChild(icon('i-arrow-left', 'ic-sm')); b.appendChild(el('span', '', T('fp.back')));
      b.addEventListener('click', function () { st.typed = d.parent; load(d.parent); }); col.appendChild(b);
    }
    d.dirs.forEach(function (n) {
      var p = join(d.path, n), c = el('button', 'fp-item'); c.type = 'button';
      c.appendChild(icon('i-folder', 'ic-sm')); c.appendChild(el('span', '', n));
      c.addEventListener('click', function () { st.typed = p; load(p); }); col.appendChild(c);
    });
    if (!d.dirs.length) col.appendChild(el('div', 'fp-empty', T('fp.no_sub')));
  }

  function add(btn, err) {
    var p = st.typed.trim(); if (!p) return;
    btn.disabled = true; err.textContent = '';
    fetch('/admin/libraries/check-folder', {
      method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ path: p, folders: opts.folders || [], library_id: opts.libraryId || 0 })
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) throw new Error(SF_I18N.msg(j) || T('fp.invalid')); return j; });
    }).then(function (j) { if (!j) return; var f = cb; close(); f(j.path); })
      .catch(function (e) { btn.disabled = false; err.textContent = e.message; });
  }

  function draw() {
    win.textContent = '';
    var head = el('div', 'em-head'); head.appendChild(icon('i-folder-plus', 'ic-sm')); head.appendChild(el('span', '', T('fp.title')));
    var x = el('button', 'em-x', '✕'); x.type = 'button'; x.setAttribute('aria-label', T('common.close')); x.addEventListener('click', close);
    head.appendChild(x); win.appendChild(head);
    var body = el('div', 'fp-body');
    var inp = el('input', 'fp-path'); inp.type = 'text'; inp.value = st.typed; inp.autocomplete = 'off'; inp.spellcheck = false;
    inp.addEventListener('input', function () { st.typed = inp.value; });
    inp.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); st.typed = inp.value.trim() || '/'; load(st.typed); } });
    body.appendChild(inp);
    var cols = el('div', 'fp-cols'), a = el('div', 'fp-col fp-side'), b = el('div', 'fp-col fp-main');
    if (st.data) { side(st.data, a); main(st.data, b); }
    cols.appendChild(a); cols.appendChild(b); body.appendChild(cols); win.appendChild(body);
    var foot = el('div', 'em-foot'), err = el('span', 'em-err', st.err || '');
    var c = el('button', 'em-btn em-cancel', T('common.cancel')); c.type = 'button'; c.addEventListener('click', close);
    var ok = el('button', 'em-btn em-ok', T('common.add')); ok.type = 'button'; ok.addEventListener('click', function () { add(ok, err); });
    foot.appendChild(err); foot.appendChild(c); foot.appendChild(ok); win.appendChild(foot);
  }

  window.sfFolderPicker = {
    open: function (o, done) {
      opts = o || {}; cb = done; st = { typed: '', path: '', data: null, err: '', first: true };
      ov = el('div', 'em-overlay fp-overlay'); win = el('div', 'em-win fp-win'); win.setAttribute('role', 'dialog'); win.setAttribute('aria-modal', 'true');
      ov.appendChild(win); document.body.appendChild(ov);
      ov.addEventListener('mousedown', function (e) { if (e.target === ov) close(); });
      document.addEventListener('keydown', onKey, true); draw(); load('');
    }
  };
});
