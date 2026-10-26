// Filtros Avançados (31.6): painel de regras sobre a biblioteca atual, com pré-visualização ao vivo (/library/<id>/smart/preview).
// window.sfAdvFilter.open('collection'|'playlist') entra no modo; getSpec() devolve {match, rules, limit} (só regras completas).
(function () {
  var bar = document.getElementById('lib-bar');
  if (!bar || !window.sfMenuAt) return;
  var lib = bar.dataset.library;
  var TXT = ['contains', 'not_contains', 'is', 'is_not'];  // rótulos: adv.field.<campo> e adv.op.<operador>
  var FIELDS = {
    title:   {t: 'text', ops: TXT},
    year:    {t: 'num', ops: ['is', 'is_not', 'gt', 'lt']},
    genre:   {t: 'text', ops: TXT},
    watched: {t: 'bool', ops: ['is', 'is_not']},
    added:   {t: 'date', ops: ['before', 'after']},
    rating:  {t: 'num', ops: ['gt', 'lt']}
  };
  function fl(k) { return T('adv.field.' + k); }
  function ol(k) { return T('adv.op.' + k); }
  var ORDER = ['title', 'year', 'genre', 'watched', 'added', 'rating'];
  var state = {match: 'all', rules: [], limit: '', target: null};
  var panel = null, xBtn = null, label = null, countEl = bar.querySelector('.lib-count'), count0 = countEl ? countEl.textContent : '';
  var token = 0, timer = null, on = false;

  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function icon(id) {
    var s = document.createElementNS('http://www.w3.org/2000/svg', 'svg'), u = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    s.setAttribute('class', 'ic'); u.setAttribute('href', '#' + id); s.appendChild(u); return s;
  }
  function genres() { try { return JSON.parse((bar.querySelector('[data-dd="genre"]') || {dataset: {}}).dataset.genres || '[]'); } catch (e) { return []; } }
  function newRule() { return {field: 'title', op: 'contains', value: ''}; }

  function selBtn(text, items) {
    var b = el('button', 'adv-sel'); b.type = 'button'; b.setAttribute('aria-haspopup', 'true');
    b.appendChild(el('span', '', text)); b.appendChild(icon('i-caret-down'));
    b.addEventListener('click', function (e) { e.stopPropagation(); window.sfMenuAt(b, items(), false, 'ctx-lib'); });
    return b;
  }

  function complete(r) { return String(r.value).trim() !== ''; }
  function spec() {
    var lim = parseInt(state.limit, 10);
    return {match: state.match, rules: state.rules.filter(complete).map(function (r) { return {field: r.field, op: r.op, value: String(r.value).trim()}; }),
            limit: lim >= 1 ? lim : null};
  }

  function render() {
    var box = panel.querySelector('.adv-rules');
    box.textContent = '';
    state.rules.forEach(function (r, i) {
      var f = FIELDS[r.field], row = el('div', 'adv-rule');
      row.appendChild(selBtn(fl(r.field), function () {
        return ORDER.map(function (k) {
          return {l: fl(k), on: k === r.field, fn: function () {
            if (k === r.field) return;
            r.field = k; r.op = FIELDS[k].ops[0]; r.value = FIELDS[k].t === 'bool' ? '1' : ''; render(); refresh();
          }};
        });
      }));
      row.appendChild(selBtn(ol(r.op), function () {
        return f.ops.map(function (k) { return {l: ol(k), on: k === r.op, fn: function () { r.op = k; render(); refresh(); }}; });
      }));
      if (f.t === 'bool') {
        row.appendChild(selBtn(T(r.value === '0' ? 'adv.no' : 'adv.yes'), function () {
          return [['1', T('adv.yes')], ['0', T('adv.no')]].map(function (o) { return {l: o[1], on: o[0] === r.value, fn: function () { r.value = o[0]; render(); refresh(); }}; });
        }));
      } else {
        var inp = el('input', 'adv-val'); inp.value = r.value; inp.setAttribute('aria-label', T('adv.value'));
        if (f.t === 'date') inp.type = 'date';
        else { inp.type = 'text'; if (f.t === 'num') inp.inputMode = 'decimal'; if (r.field === 'genre') { inp.setAttribute('list', 'adv-genres'); } }
        inp.addEventListener('input', function () { r.value = inp.value; refresh(); });
        row.appendChild(inp);
      }
      var rm = el('button', 'adv-ic adv-rm'); rm.type = 'button'; rm.setAttribute('aria-label', T('adv.remove_rule')); rm.dataset.tip = T('adv.remove_rule');
      rm.appendChild(icon('i-minus'));
      rm.addEventListener('click', function () { state.rules.splice(i, 1); render(); refresh(); });
      row.appendChild(rm);
      box.appendChild(row);
    });
    var m = panel.querySelector('.adv-match span'); if (m) m.textContent = T(state.match === 'any' ? 'adv.match_any' : 'adv.match_all');
  }

  function paint(ids, total) {
    var set = ids ? new Set(ids) : null;
    [].forEach.call(document.querySelectorAll('.pcard[data-pick]'), function (c) { c.hidden = !!set && !set.has(parseInt(c.dataset.pick, 10)); });
    if (countEl) countEl.textContent = set ? String(total) : count0;
  }

  function refresh() {
    clearTimeout(timer);
    timer = setTimeout(async function () {
      var mine = ++token, err = panel.querySelector('.adv-err');
      try {
        var r = await fetch('/library/' + lib + '/smart/preview?spec=' + encodeURIComponent(JSON.stringify(spec())));
        if (r.status === 401) { location.href = '/login'; return; }
        var j = {}; try { j = await r.json(); } catch (e) {}
        if (mine !== token || !on) return;
        if (!r.ok) { err.textContent = SF_I18N.msg(j) || T('adv.filter_fail'); err.hidden = false; return; }
        err.hidden = true; paint(j.ids, j.total);
      } catch (e) { if (mine === token) { err.textContent = T('adv.server_down'); err.hidden = false; } }
    }, 250);
  }

  function build() {
    panel = el('div', 'adv-panel'); panel.hidden = true;
    var head = el('div', 'adv-head');
    head.appendChild(selBtn(T('adv.match_all'), function () {
      return [['all', T('adv.match_all')], ['any', T('adv.match_any')]].map(function (o) {
        return {l: o[1], on: o[0] === state.match, fn: function () { state.match = o[0]; render(); refresh(); }};
      });
    }));
    head.firstChild.classList.add('adv-match');
    var add = el('button', 'adv-ic'); add.type = 'button'; add.dataset.tip = T('adv.add_rule'); add.setAttribute('aria-label', T('adv.add_rule')); add.appendChild(icon('i-plus'));
    add.addEventListener('click', function () { if (state.rules.length < 20) { state.rules.push(newRule()); render(); } });
    head.appendChild(add);
    var dots = el('button', 'adv-ic'); dots.type = 'button'; dots.dataset.tip = T('nav.more'); dots.setAttribute('aria-haspopup', 'true'); dots.setAttribute('aria-label', T('nav.more'));
    dots.appendChild(icon('i-dots-v'));
    dots.addEventListener('click', function (e) {
      e.stopPropagation();
      window.sfMenuAt(dots, [{l: T('adv.clear_rules'), fn: function () {
        state.match = 'all'; state.rules = [newRule()]; state.limit = ''; panel.querySelector('.adv-lim').value = ''; render(); refresh();
      }}], false, 'ctx-lib');
    });
    head.appendChild(dots);
    panel.appendChild(head);
    panel.appendChild(el('div', 'adv-rules'));
    var foot = el('div', 'adv-foot');
    foot.appendChild(el('span', 'adv-lim-l', T('adv.limit')));
    var lim = el('input', 'adv-lim'); lim.inputMode = 'numeric'; lim.maxLength = 5; lim.setAttribute('aria-label', T('adv.limit_aria'));
    lim.addEventListener('input', function () { lim.value = lim.value.replace(/\D/g, ''); state.limit = lim.value; refresh(); });
    foot.appendChild(lim);
    var split = el('div', 'adv-save');
    var main = el('button', 'adv-save-main', T('adv.save_as')); main.type = 'button';
    var caret = el('button', 'adv-save-caret'); caret.type = 'button'; caret.setAttribute('aria-haspopup', 'true'); caret.setAttribute('aria-label', T('adv.choose_type'));
    caret.appendChild(icon('i-caret-down'));
    main.addEventListener('click', askName);
    caret.addEventListener('click', function (e) {
      e.stopPropagation();
      var items = [];
      if (window.sfAdmin) items.push({l: T('adv.target.collection'), on: state.target === 'collection', fn: function () { state.target = 'collection'; }});
      items.push({l: T('adv.target.playlist'), on: state.target === 'playlist', fn: function () { state.target = 'playlist'; }});
      window.sfMenuAt(caret, items, false, 'ctx-lib ctx-right');
    });
    split.appendChild(main); split.appendChild(caret); foot.appendChild(split);
    panel.appendChild(foot);
    var err = el('div', 'adv-err'); err.hidden = true; panel.appendChild(err);
    var dl = el('datalist'); dl.id = 'adv-genres';
    genres().forEach(function (g) { var o = el('option'); o.value = g; dl.appendChild(o); });
    panel.appendChild(dl);
    bar.parentNode.insertBefore(panel, bar.nextSibling);

    var filters = bar.querySelector('.lib-filters');
    xBtn = el('button', 'adv-x'); xBtn.type = 'button'; xBtn.setAttribute('aria-label', T('adv.exit')); xBtn.dataset.tip = T('adv.exit');
    xBtn.appendChild(icon('i-close')); xBtn.hidden = true;
    xBtn.addEventListener('click', close);
    label = el('span', 'adv-lab', T('adv.title')); label.hidden = true;
    filters.insertBefore(label, filters.firstChild); filters.insertBefore(xBtn, filters.firstChild);
  }

  // ---- Salvar como… (31.7): pede o nome e salva como coleção (31.3) ou lista de reprodução (31.4) inteligente ----
  var dlg = null, dName = null, dTitle = null, dErr = null, saving = false;
  var TARGETS = {collection: ['adv.smart.collection', '/admin/collections'], playlist: ['adv.smart.playlist', '/playlists']};
  function toast(msg) {
    var t = document.querySelector('.sel-toast.adv-toast');
    if (!t) { t = el('div', 'sel-toast adv-toast'); document.body.appendChild(t); }
    t.textContent = msg; t.hidden = false; clearTimeout(t._t); t._t = setTimeout(function () { t.hidden = true; }, 3500);
  }
  function dlgClose() { if (dlg) dlg.hidden = true; }
  function askName() {
    var err = panel.querySelector('.adv-err');
    if (!spec().rules.length) { err.textContent = T('adv.need_rule'); err.hidden = false; return; }
    err.hidden = true;
    if (!dlg) {
      dlg = el('div', 'em-overlay'); dlg.hidden = true;
      dlg.innerHTML = '<div class="em-win em-small ca-win adv-dlg"><div class="em-head"><span></span><button type="button" class="em-x" aria-label="">✕</button></div>' +
        '<div class="adv-dlg-err" hidden></div>' +
        '<div class="em-foot ca-foot"><input type="text" class="em-q ca-name" maxlength="100" aria-label=""><button type="button" class="em-btn em-save"></button></div></div>';
      document.body.appendChild(dlg);
      dTitle = dlg.querySelector('.em-head span'); dName = dlg.querySelector('.ca-name'); dErr = dlg.querySelector('.adv-dlg-err');
      dlg.querySelector('.em-x').addEventListener('click', dlgClose);
      dlg.querySelector('.em-save').addEventListener('click', save);
      dName.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); save(); } });
      dlg.addEventListener('mousedown', function (e) { if (e.target === dlg) dlgClose(); });
      document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !dlg.hidden) { e.stopImmediatePropagation(); dlgClose(); } }, true);
    }
    if (state.target === 'collection' && !window.sfAdmin) state.target = 'playlist';
    dlg.querySelector('.em-x').setAttribute('aria-label', T('common.close')); dName.setAttribute('aria-label', T('adv.name')); dlg.querySelector('.em-save').textContent = T('common.save');
    dTitle.textContent = T('adv.save_title', {type: T(TARGETS[state.target][0])});
    dName.value = (bar.dataset.libName || '').slice(0, 100); dErr.hidden = true;
    dlg.hidden = false; dName.focus(); dName.select();
  }
  async function save() {
    var name = dName.value.trim().slice(0, 100);
    if (!name || saving) return;
    saving = true;
    var target = state.target, s = spec();
    try {
      var r = await fetch(TARGETS[target][1], {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({title: name, library_id: parseInt(lib, 10), smart: true, match: s.match, rules: s.rules, limit: s.limit})});
      if (r.status === 401) { location.href = '/login'; return; }
      var j = {}; try { j = await r.json(); } catch (e) {}
      if (!r.ok) { dErr.textContent = SF_I18N.msg(j) || T('adv.save_fail'); dErr.hidden = false; return; }
      dlgClose();
      if (target === 'collection') { location.href = '/collection/' + j.id; return; }
      close();
      toast(Tn('adv.playlist_saved', j.n, {title: j.title}));
    } catch (e) { dErr.textContent = T('adv.server_down'); dErr.hidden = false; }
    finally { saving = false; }
  }

  function open(target) {
    if (!panel) build();
    state = {match: 'all', rules: [newRule()], limit: '', target: target};
    panel.querySelector('.adv-lim').value = '';
    on = true; panel.hidden = false; xBtn.hidden = false; label.hidden = false;
    bar.classList.add('adv-on'); document.body.classList.add('adv-mode');
    render(); refresh();
  }
  function close() {
    if (!on) return;
    on = false; token++; clearTimeout(timer);
    panel.hidden = true; xBtn.hidden = true; label.hidden = true;
    bar.classList.remove('adv-on'); document.body.classList.remove('adv-mode');
    paint(null);
  }

  window.sfAdvFilter = {open: open, close: close, getSpec: spec, target: function () { return state.target; }, active: function () { return on; }};
})();
