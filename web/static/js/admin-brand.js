// 59.1: Configurações → Servidor: logo do site e animação inicial (trocar, restaurar, ligar/desligar, duração)
(function () {
  var $ = function (i) { return document.getElementById(i); }, msg = $('br-msg');
  var on = $('br-intro-on'), sec = $('br-sec'), secRow = $('br-sec-row');
  function say(t, bad) { msg.textContent = t || ''; msg.className = 'hl-msg' + (bad ? ' bad' : ''); }
  function json(r) { return r.json().then(function (j) { if (!r.ok) throw new Error(SF_I18N.msg(j) || T('common.error')); return j; }); }
  function preview(box, it, fallback) {
    box.textContent = '';
    if (!it) { if (fallback) box.appendChild(fallback()); return; }
    var el;
    if (it.kind === 'video') { el = document.createElement('video'); el.muted = true; el.loop = true; el.autoplay = true; el.playsInline = true; }
    else el = document.createElement('img');
    el.src = it.url; box.appendChild(el);
  }
  function fill(d) {
    preview($('br-logo-prev'), d.logo, function () { var a = document.createElement('span'); a.className = 'logo'; a.innerHTML = 'Star<span>Flix</span>'; return a; });
    preview($('br-intro-prev'), d.intro, function () { var t = document.createElement('span'); t.textContent = T('brand.default_anim'); return t; });
    $('br-logo-del').hidden = !d.logo; $('br-intro-del').hidden = !d.intro;
    on.checked = d.intro_on; on.disabled = false; sec.value = d.sec; sec.disabled = false;
    secRow.hidden = !(d.intro && d.intro.kind === 'image');
  }
  function upload(kind) {
    var f = $('br-' + kind + '-file').files[0]; if (!f) return;
    var fd = new FormData(); fd.append('file', f); say(T('common.sending'));
    fetch('/admin/server/brand/' + kind, {method: 'POST', body: fd}).then(json)  .then(function (j) { fill(j); say(T('common.saved')); })
      .catch(function (e) { say(e.message, true); }).then(function () { $('br-' + kind + '-file').value = ''; });
  }
  ['logo', 'intro'].forEach(function (k) {
    $('br-' + k + '-pick').addEventListener('click', function () { $('br-' + k + '-file').click(); });
    $('br-' + k + '-file').addEventListener('change', function () { upload(k); });
    $('br-' + k + '-del').addEventListener('click', function () {
      var go = function () { fetch('/admin/server/brand/' + k + '/remove', {method: 'POST'}).then(json).then(function (j) { fill(j); say(T('brand.restored')); }).catch(function (e) { say(e.message, true); }); };
      if (window.sfConfirm) window.sfConfirm(T(k === 'logo' ? 'brand.confirm_logo' : 'brand.confirm_intro'), {title: T('brand.reset'), ok: T('brand.restore')}).then(function (y) { if (y) go(); }); else go();
    });
  });
  function opts(body) {
    fetch('/admin/server/brand/options', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)})
        .then(json).then(function (j) { fill(j); say(T('common.saved')); }).catch(function (e) { say(e.message, true); fetch('/admin/server/brand').then(json).then(fill); });
  }
  on.addEventListener('change', function () { opts({intro_on: on.checked}); });
  sec.addEventListener('change', function () { opts({sec: parseInt(sec.value, 10)}); });
  on.disabled = sec.disabled = true;
  (window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () { return fetch('/admin/server/brand'); }).then(json).then(fill).catch(function (e) { say(e.message, true); });
})();
