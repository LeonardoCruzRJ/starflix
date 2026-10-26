// Abas Tags e Rótulos (23.21): campos de chips (× remove; Enter/vírgula adiciona); cadeado trava contra o scan/TMDB.
(window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () {
  var LABELS = {directors: T('et.directors'), country: T('et.country'), genres: T('et.genres'), writers: T('et.writers'), producers: T('et.producers'), label: T('et.label')};
  var LOCK = {directors: 'director', writers: 'writer', producers: 'producer', genres: 'genres', country: 'country'};
  var ORDER = {episode: ['writers', 'directors']};
  var DEF = ['directors', 'country', 'genres', 'writers', 'producers'];

  function chips(pane, data, api, key) {
    var cur = (api.changes.tags && api.changes.tags[key]) ? api.changes.tags[key].slice() : (data.tags[key] || []).slice(),
        wrap = document.createElement('div'), box = document.createElement('div'), inp = document.createElement('input'),
        lab = document.createElement('div'), line = document.createElement('div'), lk = LOCK[key], on = false, lock = null;
    wrap.className = 'em-field'; box.className = 'em-chips'; lab.className = 'em-lab'; line.className = 'em-row'; lab.textContent = LABELS[key];
    if (lk) {
      on = api.changes.locks && lk in api.changes.locks ? !!api.changes.locks[lk] : !!data.locks[lk];
      lock = document.createElement('button'); lock.type = 'button';
      var paint = function () { lock.textContent = on ? '🔒' : '🔓'; lock.classList.toggle('on', on); };
      paint();
      lock.addEventListener('click', function () { on = !on; paint(); api.lock(lk, on); });
      line.appendChild(lock);
    }
    function commit() {
      (api.changes.tags = api.changes.tags || {})[key] = cur.slice();
      api.markDirty();
      if (lk && !on) { on = true; paint(); api.lock(lk, 1); }
    }
    function draw() {
      box.innerHTML = '';
      cur.forEach(function (n, i) {
        var c = document.createElement('span'); c.className = 'em-chip';
        var x = document.createElement('button'); x.type = 'button'; x.textContent = '×'; x.setAttribute('aria-label', T('common.remove'));
        x.addEventListener('click', function () { cur.splice(i, 1); commit(); draw(); });
        c.appendChild(x); c.appendChild(document.createTextNode(n)); box.appendChild(c);
      });
      box.appendChild(inp);
    }
    function add() {
      var v = inp.value.replace(/,/g, '').trim(); inp.value = '';
      if (v && cur.indexOf(v) < 0) { cur.push(v); commit(); draw(); inp.focus(); }
    }
    inp.type = 'text'; inp.placeholder = T('et.add');
    inp.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); add(); }
      else if (e.key === 'Backspace' && !inp.value && cur.length) { cur.pop(); commit(); draw(); inp.focus(); }
    });
    inp.addEventListener('blur', add);
    box.addEventListener('click', function () { inp.focus(); });
    draw();
    line.appendChild(box); wrap.appendChild(lab); wrap.appendChild(line); pane.appendChild(wrap);
  }
  window.sfEditTabs.tags = {render: function (pane, data, api) {
    (ORDER[data.kind] || DEF).forEach(function (k) { chips(pane, data, api, k); });
  }};
  window.sfEditTabs.labels = {render: function (pane, data, api) { chips(pane, data, api, 'label'); }};
});
