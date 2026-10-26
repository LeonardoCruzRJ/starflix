// Página /admin/home: ordem (arrastar e soltar), seções ligadas, fileiras do TMDB (TMDB1…) e máximo de fileiras do Início.
(window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () {
  'use strict';
  var list = document.getElementById('hl-list');
  if (!list) return;
  var cnt = document.getElementById('hl-count'), tmdbSel = document.getElementById('hl-tmdb'), maxIn = document.getElementById('hl-max');
  var saveBtn = document.getElementById('hl-save'), resetBtn = document.getElementById('hl-reset'), msgEl = document.getElementById('hl-msg');
  var NS = 'http://www.w3.org/2000/svg';
  var items = [], tmdb = 0, tmdbMax = 8, saved = false, dirty = false, busy = false;

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
  function say(t, bad) { msgEl.textContent = t || ''; msgEl.classList.toggle('bad', !!bad); }
  function setDirty(v) { dirty = v; saveBtn.disabled = busy || !v; if (v) say(''); }
  function lock(v) { busy = v; saveBtn.disabled = v || !dirty; resetBtn.disabled = v || !saved && !dirty; tmdbSel.disabled = maxIn.disabled = v; }

  function load(j) {
    items = j.items; tmdb = j.tmdb; tmdbMax = j.tmdb_max; saved = j.saved;
    tmdbSel.textContent = '';
    for (var i = 0; i <= tmdbMax; i++) { var o = el('option', '', i === 0 ? T('hl.none') : String(i)); o.value = i; tmdbSel.appendChild(o); }
    tmdbSel.value = tmdb; maxIn.max = j.max_rows_limit; maxIn.value = j.max_rows;
    dirty = false; lock(false); render();
  }

  function count() {
    var n = items.filter(function (x) { return x.on; }).length;
    cnt.textContent = Tn('hl.count', n);
  }

  function render() {
    count();
    list.textContent = '';
    items.forEach(function (it) {
      var row = el('div', 'hl-row' + (it.on ? '' : ' off')); row.setAttribute('data-key', it.key);
      var grip = el('button', 'hl-grip'); grip.type = 'button'; grip.setAttribute('aria-label', T('hl.drag_aria', {label: it.label})); grip.setAttribute('data-tip', T('hl.drag')); grip.appendChild(icon('i-grip'));
      var ck = el('input'); ck.type = 'checkbox'; ck.checked = it.on; ck.setAttribute('aria-label', T('hl.show_aria', {label: it.label}));
      ck.addEventListener('change', function () { it.on = ck.checked; row.classList.toggle('off', !it.on); count(); setDirty(true); });
      var name = el('span', 'hl-name', it.label);
      row.appendChild(grip); row.appendChild(ck); row.appendChild(name);
      if (it.tmdb) row.appendChild(el('span', 'hl-tag', 'TMDB'));
      wireDrag(row, grip);
      list.appendChild(row);
    });
  }

  function syncFromDom() {
    var by = {}; items.forEach(function (x) { by[x.key] = x; });
    items = Array.prototype.map.call(list.children, function (r) { return by[r.getAttribute('data-key')]; });
  }

  // arrastar e soltar por ponteiro (mouse e toque) + setas ↑/↓ com a alça em foco.
  // A captura fica na lista (que não sai do DOM); a alça muda de lugar a cada troca e perderia a captura.
  function wireDrag(row, grip) {
    grip.addEventListener('pointerdown', function (e) {
      if (e.button != null && e.button !== 0) return;
      e.preventDefault();
      var id = e.pointerId;
      try { list.setPointerCapture(id); } catch (x) { /* sem captura */ }
      row.classList.add('drag');
      var move = function (ev) {
        if (ev.pointerId !== id) return;
        var next = null, rows = list.children;
        for (var i = 0; i < rows.length; i++) {
          if (rows[i] === row) continue;
          var b = rows[i].getBoundingClientRect();
          if (ev.clientY < b.top + b.height / 2) { next = rows[i]; break; }
        }
        if (next !== row.nextSibling) list.insertBefore(row, next);
        if (ev.clientY < 70) window.scrollBy(0, -14); else if (ev.clientY > window.innerHeight - 70) window.scrollBy(0, 14);
      };
      var up = function (ev) {
        if (ev.pointerId !== id) return;
        list.removeEventListener('pointermove', move); list.removeEventListener('pointerup', up); list.removeEventListener('pointercancel', up);
        try { list.releasePointerCapture(id); } catch (x) { /* já solta */ }
        row.classList.remove('drag'); syncFromDom(); setDirty(true);
      };
      list.addEventListener('pointermove', move); list.addEventListener('pointerup', up); list.addEventListener('pointercancel', up);
    });
    grip.addEventListener('keydown', function (e) {
      if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
      e.preventDefault();
      var sib = e.key === 'ArrowUp' ? row.previousSibling : row.nextSibling;
      if (!sib) return;
      if (e.key === 'ArrowUp') list.insertBefore(row, sib); else list.insertBefore(sib, row);
      syncFromDom(); setDirty(true); grip.focus();
    });
  }

  // quantidade de fileiras do TMDB: acrescenta/remove os slots TMDBn (os novos entram depois do último existente)
  tmdbSel.addEventListener('change', function () {
    var n = parseInt(tmdbSel.value, 10) || 0;
    var cur = items.filter(function (x) { return x.tmdb; });
    if (n < cur.length) {
      var gone = {}; cur.slice(n).forEach(function (x) { gone[x.key] = 1; });
      items = items.filter(function (x) { return !gone[x.key]; });
    } else {
      var at = items.length, last = -1;
      items.forEach(function (x, i) { if (x.tmdb) last = i; });
      if (last >= 0) at = last + 1;
      for (var k = cur.length + 1; k <= n; k++) { items.splice(at++, 0, { key: 'tmdb_slot_' + k, label: 'TMDB' + k, tmdb: true, on: true }); }
    }
    tmdb = n; render(); setDirty(true);
  });
  maxIn.addEventListener('input', function () { setDirty(true); });

  saveBtn.addEventListener('click', function () {
    var mx = parseInt(maxIn.value, 10);
    if (!(mx >= 1)) { say(T('hl.max_err', {max: maxIn.max}), true); return; }
    lock(true); say(T('common.saving'));
    api('/admin/home/save', {
      order: items.map(function (x) { return x.key; }),
      hidden: items.filter(function (x) { return !x.on; }).map(function (x) { return x.key; }),
      tmdb: tmdb, max_rows: mx
    }).then(function (j) { load(j); say(T('common.saved')); }).catch(function (e) { lock(false); say(e.message, true); });
  });
  resetBtn.addEventListener('click', function () {
    sfConfirm(T('hl.restore_q'), {title: T('brand.reset'), ok: T('brand.restore')}).then(function (ok) {
      if (!ok) return;
      lock(true); say(T('common.restoring'));
      api('/admin/home/reset', {}).then(function (j) { load(j); say(T('brand.restored')); }).catch(function (e) { lock(false); say(e.message, true); });
    });
  });

  api('/admin/home/data').then(load).catch(function (e) { list.textContent = ''; list.appendChild(el('p', 'la-empty', e.message)); });
});
