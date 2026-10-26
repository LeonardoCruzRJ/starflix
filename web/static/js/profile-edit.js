(function () {
  'use strict';
  function el(t, c, x) { var e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; }
  function show(row, v) {
    var box = row.querySelector('.pe-val'); box.textContent = '';
    if (row.dataset.type === 'check') { box.textContent = v === '1' ? row.dataset.label : row.dataset.tOff; return; }
    if (v) {
      if (row.dataset.field === 'link') { var a = el('a', null, v); a.href = v; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.className = 'pe-link'; box.appendChild(a); }
      else box.textContent = v;
    } else { box.textContent = row.dataset.empty; box.classList.add('pe-empty'); return; }
    box.classList.remove('pe-empty');
  }
  function edit(row) {
    var act = row.querySelector('.pe-act'), val = row.querySelector('.pe-val'), cur = row.dataset.value;
    var type = row.dataset.type, input, box = el('div', 'pe-edit');
    if (type === 'check') {
      var lb = el('label', 'pe-check'); input = el('input'); input.type = 'checkbox'; input.checked = cur === '1';
      lb.appendChild(input); lb.appendChild(document.createTextNode(' ' + row.dataset.label)); box.appendChild(lb);
    } else {
      input = type === 'area' ? el('textarea') : el('input'); if (type !== 'area') input.type = 'text';
      if (type === 'area') input.rows = 4; input.value = cur; input.maxLength = +row.dataset.max;
      input.autocomplete = 'off'; if (row.dataset.nocap) { input.setAttribute('autocapitalize', 'off'); input.setAttribute('autocorrect', 'off'); input.spellcheck = false; } box.appendChild(input);
      if (row.dataset.help) box.appendChild(el('p', 'pe-help', row.dataset.help));
    }
    var err = el('p', 'pe-err'), save = el('button', 'pe-save', T('common.save_changes')); save.type = 'button'; save.disabled = true;
    var foot = el('div', 'pe-foot'); foot.appendChild(err); foot.appendChild(save); box.appendChild(foot);
    val.hidden = true; row.appendChild(box); act.textContent = T('common.cancel');
    function value() { return type === 'check' ? (input.checked ? '1' : '0') : input.value.trim(); }
    function done() { box.remove(); val.hidden = false; act.textContent = T('common.edit'); row._open = false; }
    input.addEventListener(type === 'check' ? 'change' : 'input', function () { save.disabled = value() === cur.trim(); });
    input.addEventListener('keydown', function (e) { if (e.key === 'Enter' && type !== 'area' && !save.disabled) save.click(); if (e.key === 'Escape') { e.stopPropagation(); done(); } });
    save.addEventListener('click', function () {
      save.disabled = true; err.textContent = '';
      fetch(row.dataset.url || '/account/profile', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({field: row.dataset.field, value: type === 'check' ? value() === '1' : value()})})
        .then(function (r) { if (r.status === 401) { location.href = '/login'; throw 0; } return r.json().then(function (j) { return [r, j]; }); })
        .then(function (a) {
          if (!a[0].ok) { err.textContent = SF_I18N.msg(a[1]) || T('common.save_failed'); save.disabled = false; return; }
          row.dataset.value = type === 'check' ? value() : (a[1].value || ''); show(row, row.dataset.value); done();
          if (row.dataset.reload) location.reload();
        }).catch(function (e) { if (e !== 0) { err.textContent = T('common.conn_failed'); save.disabled = false; } });
    });
    row._open = true; input.focus();
  }
  document.querySelectorAll('.pe-row[data-field]').forEach(function (row) {
    show(row, row.dataset.value);
    row.querySelector('.pe-act').addEventListener('click', function (e) {
      e.preventDefault();
      if (row._open) { row.querySelector('.pe-edit').remove(); row.querySelector('.pe-val').hidden = false; this.textContent = T('common.edit'); row._open = false; }
      else edit(row);
    });
  });
  var pe = document.getElementById('pe-photo-edit');
  if (pe) pe.addEventListener('click', function (e) {
    e.preventDefault(); var im = document.querySelector('.pe-photo');
    var host = document.querySelector('.pe');  // em /account não há .pe (envia para /account/avatar, o padrão do editor)
    if (window.sfAvatarEditor) sfAvatarEditor.open(null, im ? im.getAttribute('src') : null, null, host && host.dataset.avurl ? {url: host.dataset.avurl} : null);
  });
})();
