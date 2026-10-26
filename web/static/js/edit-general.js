// Aba Geral (23.19): um campo por linha com cadeado; digitar trava, clicar no cadeado alterna.
(window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () {
  var SPEC = {
    title: [T('pl.field.title'), 'text'], sort_title: [T('eg.sort_title'), 'text'], original_title: [T('eg.original_title'), 'text'],
    release_date: [T('eg.release'), 'date'], air_date: [T('eg.release'), 'date'],
    content_rating: [T('eg.content_rating'), 'text'], rating: [T('eg.rating'), 'number'], overview: [T('pl.field.summary'), 'area']
  };
  var ORDER = ['title', 'sort_title', 'original_title', 'release_date', 'air_date', 'content_rating', 'rating', 'overview'];
  window.sfEditTabs.general = {
    render: function (pane, data, api) {
      ORDER.forEach(function (k) {
        if (!(k in data.fields)) return;
        var s = SPEC[k], row = document.createElement('div'), lab = document.createElement('div'), line = document.createElement('div'),
            inp = document.createElement(s[1] === 'area' ? 'textarea' : 'input'), lock = document.createElement('button');
        row.className = 'em-field'; lab.className = 'em-lab'; line.className = 'em-row'; lab.textContent = s[0];
        if (s[1] !== 'area') inp.type = s[1];
        if (s[1] === 'number') { inp.min = 0; inp.max = 10; inp.step = 0.1; }
        if (s[1] === 'area') inp.rows = 6;
        var v = (api.changes.fields && k in api.changes.fields) ? api.changes.fields[k] : data.fields[k];
        inp.value = v == null ? '' : v;
        var on = api.changes.locks && k in api.changes.locks ? !!api.changes.locks[k] : !!data.locks[k];
        function paint() { lock.textContent = on ? '🔒' : '🔓'; lock.classList.toggle('on', on); lock.title = on ? T('eg.locked') : T('eg.unlocked'); }
        lock.type = 'button'; paint();
        inp.addEventListener('input', function () { on = true; paint(); api.field(k, inp.value); });
        lock.addEventListener('click', function () { on = !on; paint(); api.lock(k, on); });
        line.appendChild(lock); line.appendChild(inp); row.appendChild(lab); row.appendChild(line); pane.appendChild(row);
      });
    }
  };
});
