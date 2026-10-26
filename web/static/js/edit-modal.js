// Modal "Editar" (23.18). Abre pelo ✎ do card (.pcard-edit) e do detalhe ([data-edit-item="tipo:ref"]).
// Abas registradas em window.sfEditTabs[nome] = {label, render(pane, data, api)} (23.19–23.24); sem renderer mostra "Em breve".
(window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () {
  var LABELS = {general: T('pl.tab.general'), tags: T('em.tab.tags'), labels: T('em.tab.labels'), poster: T('pl.tab.poster'), backdrop: T('pl.tab.backdrop'),
    logo: T('pl.tab.logo'), square: T('pl.tab.square'), info: T('em.tab.info'), advanced: T('em.tab.advanced')};
  window.sfEditTabs = window.sfEditTabs || {};
  var el = document.getElementById('em'); if (!el) return;
  var tabs = document.getElementById('em-tabs'), pane = document.getElementById('em-pane'),
      err = document.getElementById('em-err'), data = null, cur = null, dirty = false;

  var api = {
    markDirty: function () { dirty = true; },
    changes: {},                       // {fields:{}, locks:{}, ...}; cada aba grava aqui o que mudou, enviado no Salvar
    set: function (k, v) { api.changes[k] = v; dirty = true; },
    field: function (k, v) { (api.changes.fields = api.changes.fields || {})[k] = v; api.lock(k, 1); },
    lock: function (k, on) { (api.changes.locks = api.changes.locks || {})[k] = on ? 1 : 0; dirty = true; }
  };

  function show(name) {
    cur = name;
    Array.prototype.forEach.call(tabs.children, function (b) { b.classList.toggle('on', b.dataset.tab === name); });
    pane.innerHTML = '';
    var t = window.sfEditTabs[name];
    if (t && t.render) t.render(pane, data, api);
    else pane.innerHTML = '<p class="em-soon"></p>'; if (!(t && t.render)) pane.firstChild.textContent = T('em.soon');
  }

  function close(force) {
    if (!force && dirty) { sfConfirm(T('common.discard_text'), {title: T('common.discard_title'), ok: T('common.close'), danger: true}).then(function (ok) { if (ok) close(true); }); return; }
    var rl = api.reload; el.hidden = true; document.documentElement.classList.remove('em-open'); data = null; dirty = false; api.changes = {}; api.reload = false;
    if (rl) location.reload();
  }

  async function open(kind, ref) {
    err.textContent = ''; dirty = false; api.changes = {};
    try {
      var r = await fetch('/admin/item/' + kind + '/' + encodeURIComponent(ref) + '/edit');
      if (r.status === 401) { location.href = '/login'; return; }
      if (!r.ok) throw 0;
      data = await r.json();
    } catch (e) { alert(T('em.load_fail')); return; }
    document.getElementById('em-title').textContent = data.title;
    tabs.innerHTML = '';
    data.tabs.forEach(function (n) {
      var b = document.createElement('button'); b.type = 'button'; b.dataset.tab = n;
      b.textContent = (data.kind === 'video' && n === 'poster') ? T('em.tab.thumb') : (window.sfEditTabs[n] && window.sfEditTabs[n].label) || LABELS[n] || n;
      b.addEventListener('click', function () { show(n); });
      tabs.appendChild(b);
    });
    el.hidden = false; document.documentElement.classList.add('em-open');
    show(data.tabs[0]);
  }
  window.sfEditOpen = open;

  async function save() {
    if (!data) return;
    err.textContent = '';
    try {
      var r = await fetch('/admin/item/' + data.kind + '/' + encodeURIComponent(data.ref) + '/edit', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(api.changes)
      });
      if (!r.ok) { var j = {}; try { j = await r.json(); } catch (e) {} err.textContent = SF_I18N.msg(j) || T('em.save_err'); return; }
      close(true); location.reload();
    } catch (e) { err.textContent = T('common.network_error'); }
  }

  function fromCard(card) {
    var a = card.querySelector('.pcard-title'), href = a ? a.getAttribute('href') : '', m;
    if (card.dataset.type === 'video' && card.dataset.id) return ['video', card.dataset.id];  // 34.6
    if (card.dataset.kind && card.dataset.id) return [card.dataset.kind, card.dataset.id];
    if ((m = href.match(/^\/show\/(\d+)\/season\/(\d+)$/))) return ['season', m[1] + '-' + m[2]];
    if ((m = href.match(/^\/show\/(\d+)$/))) return ['show', m[1]];
    if ((m = href.match(/^\/movie\/(\d+)$/))) return ['movie', m[1]];
    return null;
  }

  window.sfCardItem = fromCard;

  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-edit]'), d = e.target.closest('[data-edit-item]');
    if (d) { e.preventDefault(); var p = d.dataset.editItem.split(':'); open(p[0], p[1]); return; }
    if (b) {
      var card = b.closest('.pcard'), k = card && fromCard(card);
      if (k) { e.preventDefault(); e.stopPropagation(); open(k[0], k[1]); }
    }
  });
  document.getElementById('em-close').addEventListener('click', function () { close(); });
  document.getElementById('em-cancel').addEventListener('click', function () { close(); });
  document.getElementById('em-save').addEventListener('click', save);
  el.addEventListener('mousedown', function (e) { if (e.target === el) close(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !el.hidden) { e.stopImmediatePropagation(); close(); } }, true);
});
