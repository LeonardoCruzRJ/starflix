(function () {
  'use strict';
  document.querySelectorAll('.st-row').forEach(function (row) {
    var act = row.querySelector('.st-act'), form = row.querySelector('.pe-edit'), vals = row.querySelectorAll('.pe-val'),
        save = row.querySelector('.pe-save'), err = row.querySelector('.pe-err'), ctl = row.querySelectorAll('[data-key]');
    function read() { var o = {}; ctl.forEach(function (c) { o[c.dataset.key] = c.type === 'checkbox' ? c.checked : c.value; }); return o; }
    var orig = JSON.stringify(read());
    function toggle(open) {
      form.hidden = !open; vals.forEach(function (v) { v.hidden = open; }); act.textContent = open ? act.dataset.tCancel : act.dataset.tEdit;
      if (!open) { ctl.forEach(function (c) { var k = c.dataset.key, o = JSON.parse(orig); if (c.type === 'checkbox') c.checked = !!o[k]; else c.value = o[k]; }); err.textContent = ''; save.disabled = true; paint(); }
    }
    var prev = row.querySelector('.sub-prev'), map = {sub_size: 'ssize', sub_color: 'scolor', sub_bg: 'sbg', sub_pos: 'spos'};
    function paint() { if (prev) ctl.forEach(function (c) { if (map[c.dataset.key]) prev.dataset[map[c.dataset.key]] = c.value; }); }
    function check() { paint(); save.disabled = JSON.stringify(read()) === orig; }
    act.addEventListener('click', function (e) { e.preventDefault(); toggle(form.hidden); });
    ctl.forEach(function (c) { c.addEventListener('change', check); });
    save.addEventListener('click', function () {
      save.disabled = true; err.textContent = '';
      var lc = row.querySelector('[data-key="lang"]');  // 59.4: o idioma vai pela API de idiomas (perfil + cookie)
      (lc ? window.SF_I18N.set(lc.value).then(function (a) { return [a, a]; }) : fetch('/account/settings', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({values: read()})})
        .then(function (r) { return r.json().then(function (j) { return [r, j]; }); }))
        .then(function (a) { if (a[0].status === 401) { location.href = '/login'; throw 0; } return a; })
        .then(function (a) { if (!a[0].ok) { err.textContent = SF_I18N.msg(a[1]) || T('common.save_failed'); check(); return; } if (lc) { orig = JSON.stringify(read()); check(); } else location.reload(); })
        .catch(function (e) { if (e !== 0) { err.textContent = T('common.conn_failed'); check(); } });
    });
  });
})();
