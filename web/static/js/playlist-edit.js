// Modal "Editar Lista de reprodução" (31.9, abas Geral · Pôster · Plano de fundo · Logo · Arte Quadrada) e "Excluir lista".
// window.sfPlaylistEdit(id) · window.sfPlaylistDelete(id, nome, urlDepois). Só o dono da lista (rotas /playlist/<id>/…).
(function () {
  var TABS = ['general', 'poster', 'backdrop', 'logo', 'square'];  // rótulos: pl.tab.<aba>
  var el = document.createElement('div'); el.className = 'em-overlay'; el.hidden = true;
  el.innerHTML = '<div class="em-win" role="dialog" aria-modal="true"><div class="em-head"><svg class="ic ic-sm"><use href="#i-edit"/></svg><span class="pe-t"></span>' +
    '<button type="button" class="em-x" aria-label="">✕</button></div><div class="em-body"><nav class="em-tabs"></nav><div class="em-pane"></div></div>' +
    '<div class="em-foot"><span class="em-err"></span><button type="button" class="em-btn em-cancel"></button>' +
    '<button type="button" class="em-btn em-save"></button></div></div>';
  document.body.appendChild(el);
  var W = el.firstChild, TT = el.querySelector('.pe-t'), tabs = el.querySelector('.em-tabs'), pane = el.querySelector('.em-pane'),
      err = el.querySelector('.em-err'), foot = el.querySelector('.em-foot'), data = null, fields = {}, dirty = false, reload = false, id = 0;

  function labels() {
    el.querySelector('.em-x').setAttribute('aria-label', T('common.close'));
    el.querySelector('.em-cancel').textContent = T('common.cancel'); el.querySelector('.em-save').textContent = T('pl.save_changes');
  }
  function hide() { el.hidden = true; document.documentElement.classList.remove('em-open'); }
  function close(force) {
    if (!force && dirty) { sfConfirm(T('common.discard_text'), {title: T('common.discard_title'), ok: T('common.close'), danger: true}).then(function (ok) { if (ok) close(true); }); return; }
    hide(); if (reload) location.reload();
    dirty = false; reload = false; data = null;
  }
  function show(name) {
    Array.prototype.forEach.call(tabs.children, function (b) { b.classList.toggle('on', b.dataset.tab === name); });
    pane.innerHTML = '';
    if (name === 'general') general(); else images(name);
  }
  function general() {
    [['title', T('pl.field.title'), 'input'], ['summary', T('pl.field.summary'), 'textarea']].forEach(function (s) {
      var row = document.createElement('div'), lab = document.createElement('div'), inp = document.createElement(s[2]);
      row.className = 'em-field'; lab.className = 'em-lab'; lab.textContent = s[1];
      if (s[2] === 'textarea') inp.rows = 6; else inp.type = 'text';
      inp.maxLength = s[0] === 'title' ? 100 : 4000;
      inp.value = s[0] in fields ? fields[s[0]] : data.fields[s[0]] || '';
      inp.addEventListener('input', function () { fields[s[0]] = inp.value; dirty = true; });
      row.appendChild(lab); row.appendChild(inp); pane.appendChild(row);
    });
  }
  function images(slot) {
    var strip = document.createElement('div'), grid = document.createElement('div'), msg = document.createElement('div'), file = document.createElement('input');
    strip.className = 'em-strip';
    strip.innerHTML = '<a href="#" data-a="file"></a> · <span></span> · <a href="#" data-a="url"></a>';
    strip.querySelector('[data-a="file"]').textContent = T('pl.pick_image'); strip.querySelector('span').textContent = T('pl.drag_drop'); strip.querySelector('[data-a="url"]').textContent = T('pl.type_url');
    file.type = 'file'; file.accept = 'image/jpeg,image/png,image/webp'; file.hidden = true;
    grid.className = 'em-grid em-grid-' + (slot === 'backdrop' ? 2 : 3) + (slot === 'logo' ? ' em-grid-logo' : '');
    msg.className = 'em-msg';
    pane.appendChild(strip); pane.appendChild(file); pane.appendChild(msg);
    if (slot === 'logo' || data.images[slot]) {
      var clr = document.createElement('a'); clr.href = '#'; clr.className = 'em-clear'; clr.textContent = T('pl.clear_image');
      clr.addEventListener('click', function (e) { e.preventDefault(); send({clear: '1'}); });
      pane.appendChild(clr);
    }
    pane.appendChild(grid);
    function tile(src) {
      var t = document.createElement('div'); t.className = 'em-tile on'; var i = document.createElement('img');
      i.src = src; i.alt = ''; i.onerror = function () { t.remove(); };
      t.appendChild(i); t.insertAdjacentHTML('beforeend', '<span class="em-ck">✓</span>'); return t;
    }
    function paint() {
      grid.innerHTML = '';
      if (data.images[slot]) grid.appendChild(tile('/playlist-image/' + id + '/' + slot + '?t=' + Date.now()));
      else if (slot === 'poster' && data.covers && data.covers.length) {  // sem capa própria: a grade 2×2 dos itens está em uso
        var t = document.createElement('div'); t.className = 'em-tile on';
        var c = document.createElement('span'); c.className = 'pl-cover pl-cover-' + Math.min(data.covers.length, 4);
        data.covers.slice(0, 4).forEach(function (m) { var i = document.createElement('img'); i.src = '/poster/' + m; i.alt = ''; c.appendChild(i); });
        t.appendChild(c); t.insertAdjacentHTML('beforeend', '<span class="em-ck">✓</span>'); grid.appendChild(t);
      }
    }
    async function send(fields2, f) {
      var fd = new FormData(); Object.keys(fields2).forEach(function (k) { fd.append(k, fields2[k]); });
      if (f) fd.append('file', f);
      msg.textContent = T('common.apply');
      try {
        var r = await fetch('/playlist/' + id + '/image/' + slot, {method: 'POST', body: fd}), j = {};
        try { j = await r.json(); } catch (e) {}
        if (r.status === 401) { location.href = '/login'; return; }
        if (!r.ok) { msg.textContent = SF_I18N.msg(j) || T('common.error'); return; }
        msg.textContent = ''; data.images[slot] = j.name || null; reload = true; show(slot);
      } catch (e) { msg.textContent = T('common.network_error'); }
    }
    strip.addEventListener('click', function (e) {
      var a = e.target.closest('a'); if (!a) return; e.preventDefault();
      if (a.dataset.a === 'file') file.click(); else { var u = prompt(T('pl.url_prompt')); if (u) send({url: u}); }
    });
    file.addEventListener('change', function () { if (file.files[0]) send({}, file.files[0]); file.value = ''; });
    pane.addEventListener('dragover', function (e) { e.preventDefault(); });
    pane.addEventListener('drop', function (e) {
      e.preventDefault();
      var f = e.dataTransfer.files && e.dataTransfer.files[0], u = e.dataTransfer.getData('text/uri-list');
      if (f) send({}, f); else if (u && /^https?:/.test(u)) send({url: u.split('\n')[0]});
    });
    paint();
  }
  async function save() {
    err.textContent = '';
    if (!Object.keys(fields).length) { close(true); return; }
    try {
      var r = await fetch('/playlist/' + id + '/edit', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({fields: fields})}), j = {};
      try { j = await r.json(); } catch (e) {}
      if (r.status === 401) { location.href = '/login'; return; }
      if (!r.ok) { err.textContent = SF_I18N.msg(j) || T('pl.save_error'); return; }
      hide(); location.reload();
    } catch (e) { err.textContent = T('common.network_error'); }
  }
  window.sfPlaylistEdit = async function (pid) {
    id = pid; fields = {}; dirty = false; reload = false; err.textContent = '';
    try {
      var r = await fetch('/playlist/' + pid + '/edit');
      if (r.status === 401) { location.href = '/login'; return; }
      if (!r.ok) throw 0;
      data = await r.json();
    } catch (e) { alert(T('pl.load_failed')); return; }
    data.covers = (window.sfPlaylist && window.sfPlaylist.ids || []).slice(0, 4);
    W.className = 'em-win'; foot.hidden = false; labels();
    TT.textContent = data.title; tabs.innerHTML = '';
    TABS.forEach(function (t) {
      var b = document.createElement('button'); b.type = 'button'; b.dataset.tab = t; b.textContent = T('pl.tab.' + t);
      b.addEventListener('click', function () { show(t); }); tabs.appendChild(b);
    });
    el.hidden = false; document.documentElement.classList.add('em-open'); show('general');
  };
  window.sfPlaylistDelete = function (pid, name, next) {
    data = null; dirty = false; reload = false; err.textContent = ''; W.className = 'em-win em-small'; foot.hidden = false; labels();
    TT.textContent = T('pl.delete_title'); tabs.innerHTML = '';
    pane.innerHTML = ''; var p = document.createElement('p'); p.textContent = T('pl.delete_text', {name: name}); pane.appendChild(p);
    el.hidden = false;
    var ok = el.querySelector('.em-save'), keep = T('pl.save_changes');
    ok.textContent = T('lib.delete'); ok.onclick = async function () {
      var r = await fetch('/playlists/' + pid, {method: 'DELETE'});
      if (r.status === 401) { location.href = '/login'; return; }
      if (r.ok) location.href = next || '/'; else err.textContent = T('pl.delete_failed');
    };
    var done = function () { ok.textContent = keep; ok.onclick = null; };
    el.addEventListener('click', function h(e) { if (e.target.closest('.em-cancel, .em-x') || e.target === el) { done(); el.removeEventListener('click', h); } });
  };

  el.querySelector('.em-x').addEventListener('click', function () { close(); });
  el.querySelector('.em-cancel').addEventListener('click', function () { close(); });
  el.querySelector('.em-save').addEventListener('click', function () { if (data) save(); });
  el.addEventListener('mousedown', function (e) { if (e.target === el) close(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !el.hidden) { e.stopImmediatePropagation(); close(); } }, true);
})();
