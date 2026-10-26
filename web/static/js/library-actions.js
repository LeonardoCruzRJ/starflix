// Modais Analisar, Atualizar todas as Informações e Esvaziar Lixeira (29.10). Registra as ações em sfLibMenu.
(function () {
  var M = window.sfLibMenu;
  if (!M) return;
  var ACT = {  // textos: lib.act.<chave>.title|ok|text
    analyze: {url: 'analyze', scan: true},
    refresh: {url: 'refresh-info', scan: true},
    trickplay: {url: 'trickplay', scan: true},
    optimize: {url: 'optimize', scan: false, queued: true},
    trash: {url: 'empty-trash', scan: false}
  };
  var ov = document.createElement('div');
  ov.className = 'em-overlay'; ov.hidden = true;
  ov.innerHTML = '<div class="em-win em-small" role="dialog" aria-modal="true" aria-labelledby="lac-t">' +
    '<div class="em-head"><span id="lac-t"></span><button type="button" class="em-x" aria-label="">✕</button></div>' +
    '<div class="em-pane"><p class="ld-text" id="lac-p"></p></div>' +
    '<div class="em-foot"><span class="em-err" id="lac-e"></span><button type="button" class="em-btn em-cancel" id="lac-c"></button>' +
    '<button type="button" class="em-btn em-ok" id="lac-x"></button></div></div>';
  document.body.appendChild(ov);
  var cur = null;
  var title = ov.querySelector('#lac-t'), p = ov.querySelector('#lac-p'), err = ov.querySelector('#lac-e'),
      ok = ov.querySelector('#lac-x'), busy = false;

  function close() { if (busy) return; ov.hidden = true; cur = null; }
  function open(k) {
    cur = ACT[k]; err.textContent = ''; ok.disabled = false;
    ov.querySelector('.em-x').setAttribute('aria-label', T('common.close')); ov.querySelector('#lac-c').textContent = T('common.cancel');
    title.textContent = T('lib.act.' + k + '.title'); p.textContent = T('lib.act.' + k + '.text'); ok.textContent = T('lib.act.' + k + '.ok');
    ov.hidden = false; ok.focus();
  }
  ov.querySelector('.em-x').addEventListener('click', close);
  ov.querySelector('#lac-c').addEventListener('click', close);
  ov.addEventListener('mousedown', function (e) { if (e.target === ov) close(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !ov.hidden) close(); });

  ok.addEventListener('click', async function () {
    if (!cur || busy) return;
    var t = cur, r, j = {};
    busy = true; ok.disabled = true; err.textContent = '';
    try {
      r = await fetch('/admin/libraries/' + M.id + '/' + t.url, {method: 'POST', headers: {Accept: 'application/json'}});
      if (r.status === 401) { location.href = '/login'; return; }
      try { j = await r.json(); } catch (e) {}
    } catch (e) { busy = false; ok.disabled = false; err.textContent = T('lib.no_conn'); return; }
    busy = false;
    if (r.status === 409) { ov.hidden = true; cur = null; M.toast(T('lib.scan_running')); return; }
    if (!r.ok) { ok.disabled = false; err.textContent = SF_I18N.msg(j) || T('lib.action_failed'); return; }
    ov.hidden = true; cur = null;
    if (t.scan) { M.started(); return; }
    if (t.queued) { var q = j.queued || 0; M.toast(q ? Tn('lib.files_queued', q) : T('lib.nothing_convert')); return; }
    var n = j.removed || 0;
    M.toast(Tn('lib.removed', n));
    if (n) M.refreshView();
  });

  M.on('analyze', function () { open('analyze'); });
  M.on('refresh', function () { open('refresh'); });
  M.on('trickplay', function () { open('trickplay'); });
  M.on('optimize', function () { open('optimize'); });
  M.on('trash', function () { open('trash'); });
})();
