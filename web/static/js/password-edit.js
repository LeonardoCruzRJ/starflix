(function () {
  'use strict';
  var act = document.getElementById('pw-act'); if (!act) return;
  var form = document.getElementById('pw-form'), val = document.getElementById('pw-val'), save = document.getElementById('pw-save'),
      err = document.getElementById('pw-err'), nw = document.getElementById('pw-new'), cf = document.getElementById('pw-conf'),
      cu = document.getElementById('pw-cur'), out = document.getElementById('pw-out');
  function reset() { nw.value = cf.value = cu.value = ''; out.checked = false; err.textContent = ''; save.disabled = true; }
  function toggle(open) { form.hidden = !open; val.hidden = open; act.textContent = open ? act.dataset.tCancel : act.dataset.tEdit; if (open) nw.focus(); else reset(); }
  function check() { save.disabled = !(nw.value && cf.value && cu.value); }
  act.addEventListener('click', function (e) { e.preventDefault(); toggle(form.hidden); });
  [nw, cf, cu].forEach(function (i) { i.addEventListener('input', check); i.addEventListener('keydown', function (e) { if (e.key === 'Enter' && !save.disabled) save.click(); if (e.key === 'Escape') { e.stopPropagation(); toggle(false); } }); });
  save.addEventListener('click', function () {
    save.disabled = true; err.textContent = '';
    fetch('/account/password', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({new: nw.value, confirm: cf.value, current: cu.value, logout_others: out.checked})})
      .then(function (r) { if (r.status === 401) { location.href = '/login'; throw 0; } return r.json().then(function (j) { return [r, j]; }); })
      .then(function (a) {
        if (!a[0].ok) { err.textContent = SF_I18N.msg(a[1]) || T('common.save_failed'); check(); return; }
        toggle(false); val.textContent = act.dataset.tChanged; setTimeout(function () { val.textContent = '••••••••'; }, 4000);
      }).catch(function (e) { if (e !== 0) { err.textContent = T('common.conn_failed'); check(); } });
  });
})();
