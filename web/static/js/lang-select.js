// 59.4: seletor de idioma das telas de entrada (sem login). Grava pela API de idiomas e recarrega no idioma novo
// 59.6: troca pelo SF_I18N.set (sem recarregar nas telas que já são ao vivo).
(function () {
  'use strict';
  var sel = document.querySelector('[data-lang-select]'); if (!sel) return;
  var cur = sel.value;
  sel.addEventListener('change', function () {
    var v = sel.value; sel.disabled = true;
    window.SF_I18N.set(v)
      .then(function (a) { if (!a.ok) throw 0; cur = v; sel.disabled = false; })
      .catch(function () { sel.value = cur; sel.disabled = false; });
  });
})();
