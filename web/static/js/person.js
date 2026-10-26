// Página da pessoa (37.x): abas da Filmografia (Ator, Aparições, Produtor...).
(function () {
  var tabs = document.querySelectorAll('.pp-tab');
  if (!tabs.length) return;
  function show(key) {
    tabs.forEach(function (t) {
      var on = t.dataset.tab === key;
      t.classList.toggle('on', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    document.querySelectorAll('.pp-rows').forEach(function (u) { u.hidden = u.dataset.panel !== key; });
  }
  tabs.forEach(function (t) { t.addEventListener('click', function () { show(t.dataset.tab); }); });
})();
