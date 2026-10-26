// Modal "Apagar Biblioteca" (29.9): checkbox de confirmação e Excluir vermelho. sfLibDelete.open(lib, onDone)
(window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () {
  var ov = document.createElement('div');
  ov.className = 'em-overlay'; ov.hidden = true;
  ov.innerHTML = '<div class="em-win em-small" role="dialog" aria-modal="true" aria-labelledby="ld-t">' +
    '<div class="em-head"><span id="ld-t">' + T('lm.del.title') + '</span><button type="button" class="em-x" aria-label="' + T('common.close') + '">✕</button></div>' +
    '<div class="em-pane"><p class="ld-text"></p><label class="ld-check"><input type="checkbox" id="ld-ck"><span></span></label></div>' +
    '<div class="em-foot"><span class="em-err" id="ld-e"></span><button type="button" class="em-btn em-cancel" id="ld-c">' + T('common.cancel') + '</button>' +
    '<button type="button" class="em-btn em-danger" id="ld-x" disabled>' + T('lib.delete') + '</button></div></div>';
  document.body.appendChild(ov);
  var txt = ov.querySelector('.ld-text'), lbl = ov.querySelector('.ld-check span'), ck = ov.querySelector('#ld-ck'),
      err = ov.querySelector('#ld-e'), dx = ov.querySelector('#ld-x'), lib = null, done = null, busy = false;

  function close() { if (busy) return; ov.hidden = true; lib = null; done = null; }
  function open(l, cb) {
    lib = l; done = cb; err.textContent = ''; ck.checked = false; dx.disabled = true;
    txt.textContent = T('lm.del.text', {name: l.name});
    lbl.textContent = T('lm.del.check', {name: l.name});
    ov.hidden = false; ck.focus();
  }
  ck.addEventListener('change', function () { dx.disabled = !ck.checked; });
  ov.querySelector('.em-x').addEventListener('click', close);
  ov.querySelector('#ld-c').addEventListener('click', close);
  ov.addEventListener('mousedown', function (e) { if (e.target === ov) close(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !ov.hidden) close(); });
  dx.addEventListener('click', async function () {
    if (!lib || !ck.checked || busy) return;
    busy = true; dx.disabled = true; err.textContent = '';
    var r, j = {};
    try {
      r = await fetch('/admin/libraries/' + lib.id + '/delete?json=1', {method: 'POST', headers: {Accept: 'application/json'}});
      if (r.status === 401) { location.href = '/login'; return; }
      try { j = await r.json(); } catch (e) {}
    } catch (e) { busy = false; dx.disabled = !ck.checked; err.textContent = T('lm.del.offline'); return; }
    busy = false;
    if (!r.ok) { dx.disabled = !ck.checked; err.textContent = SF_I18N.msg(j) || T('lm.del.fail'); return; }
    var cb = done, l = lib; ov.hidden = true; lib = null; done = null;
    if (cb) cb(l);
  });
  window.sfLibDelete = {open: open};
});
