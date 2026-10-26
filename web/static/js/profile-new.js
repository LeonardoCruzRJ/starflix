// Novo perfil (54.23): nome + foto (recorte pelo avatar-editor.js, sem enviar); Salvar cria o perfil (POST /profiles/create), envia a foto (POST /profiles/<id>/avatar) e volta para a escolha de perfil.
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var name = $('swn-name'), save = $('swn-save'), err = $('swn-err'), count = $('swn-count'), sheet = $('swn-sheet'),
      img = $('swn-img'), letter = $('swn-letter'), rm = $('swn-rm'), blob = null;
  function sync() {
    var v = name.value.trim();
    letter.textContent = v ? v.charAt(0).toUpperCase() : '?';
    count.textContent = name.value.length + ' / 30';
    save.disabled = !v;
  }
  function setPhoto(b, url) {
    blob = b; img.hidden = !b; if (b) img.src = url; else img.removeAttribute('src');
    letter.hidden = !!b; rm.hidden = !b;
  }
  name.addEventListener('input', sync);
  name.addEventListener('keydown', function (e) { if (e.key === 'Enter' && !save.disabled) save.click(); });
  $('swn-pick').addEventListener('click', function () { sheet.hidden = false; });
  sheet.addEventListener('click', function (e) { if (e.target === sheet) sheet.hidden = true; });
  sheet.querySelectorAll('[data-pick]').forEach(function (b) {
    b.addEventListener('click', function () {
      if (b.dataset.pick === 'rm') { setPhoto(null); sheet.hidden = true; return; }
      $(b.dataset.pick === 'cam' ? 'swn-file-cam' : 'swn-file-lib').click();
    });
  });
  ['swn-file-cam', 'swn-file-lib'].forEach(function (id) {
    var inp = $(id);
    inp.addEventListener('change', function () {
      var f = inp.files && inp.files[0]; inp.value = ''; if (!f) return;
      sheet.hidden = true;
      sfAvatarEditor.open(null, null, f, {onBlob: function (b, url) { if (b) setPhoto(b, url); }});
    });
  });
  save.addEventListener('click', function () {
    save.disabled = true; err.textContent = '';
    fetch('/profiles/create', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name: name.value})})
      .then(function (r) { if (r.status === 401) { location.href = '/login'; throw 0; } return r.json().then(function (j) { return [r, j]; }); })
      .then(function (a) {
        if (!a[0].ok) { err.textContent = SF_I18N.msg(a[1]) || T('common.save_failed'); save.disabled = false; return; }
        var id = a[1].id;
        if (!blob) { location.href = '/profiles'; return; }
        var fd = new FormData(); fd.append('file', blob, 'avatar.jpg');
        return fetch('/profiles/' + id + '/avatar', {method: 'POST', body: fd}).then(function (r) {
          location.href = r.ok ? '/profiles' : '/profiles/' + id + '/edit';  // foto falhou: abre a edição para tentar de novo
        });
      }).catch(function (e) { if (e !== 0) { err.textContent = T('common.conn_failed'); save.disabled = false; } });
  });
  sync();
})();
