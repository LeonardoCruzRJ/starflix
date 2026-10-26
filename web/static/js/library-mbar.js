// 54.14: barra superior das bibliotecas no celular — toque num ícone abre o popup (Recomendado / Biblioteca / Coleções) com a pontinha apontando para ele
// 54.16: o toque no ícone também entra direto no Recomendado daquela biblioteca (a página abre já com o popup e Recomendado marcado); só tocar em Biblioteca/Coleções no popup muda a tela
(function () {
  var bar = document.getElementById('m-libbar'), pop = document.getElementById('m-libpop');
  if (!bar || !pop) return;
  var tip = pop.querySelector('.m-libpop-tip'), links = pop.querySelectorAll('a'), openBtn = null;
  var curLib = bar.dataset.cur, curTab = bar.dataset.tab;
  try { localStorage.setItem('sf.lastlib', curLib); } catch (e) {}
  var on = bar.querySelector('button.on'); if (on && on.scrollIntoView) { try { on.scrollIntoView({inline: 'center', block: 'nearest'}); } catch (e) {} }
  var KEY = 'sf.libpop', guard = 0;  // guard: logo após abrir sozinho, rolagem/resize do carregamento não fecham o popup
  function close() { pop.hidden = true; if (openBtn) openBtn.setAttribute('aria-expanded', 'false'); openBtn = null; }
  function place(btn) {
    var r = btn.getBoundingClientRect(), vw = document.documentElement.clientWidth;
    pop.style.left = '0px'; pop.hidden = false;
    var pw = pop.offsetWidth, center = r.left + r.width / 2;
    var left = Math.max(8, Math.min(center - pw / 2, vw - pw - 8));
    pop.style.left = left + 'px';
    tip.style.left = Math.max(16, Math.min(center - left, pw - 16)) + 'px';
  }
  function open(btn) {
    var id = btn.dataset.lib;
    links.forEach(function (a) {
      var t = a.dataset.t;
      a.setAttribute('href', '/library/' + id + '?tab=' + t);
      a.classList.toggle('on', id === curLib && t === curTab);
      if (t === 'collections') a.hidden = btn.dataset.cols !== '1';  // sem coleção, sem o ícone
    });
    openBtn = btn; btn.setAttribute('aria-expanded', 'true'); place(btn);
  }
  bar.addEventListener('click', function (e) {
    var btn = e.target.closest('button[data-lib]'); if (!btn) return;
    if (openBtn === btn) { close(); return; }
    close();
    var id = btn.dataset.lib;
    if (id === curLib && curTab === 'recommended') { open(btn); return; }  // já está no Recomendado desta biblioteca: só abre o popup
    // outra biblioteca (ou outra aba): entra direto no Recomendado e a página nova abre o popup
    try { sessionStorage.setItem(KEY, id); } catch (err) {}
    location.href = '/library/' + id + '?tab=recommended';
  });
  pop.addEventListener('click', function (e) {
    var a = e.target.closest('a'); if (!a) return;
    if (a.classList.contains('on')) { e.preventDefault(); close(); }  // já é a tela atual: só fecha
  });
  // chegou pelo toque num ícone: abre o popup apontando para a biblioteca atual, com Recomendado marcado
  var want = null; try { want = sessionStorage.getItem(KEY); sessionStorage.removeItem(KEY); } catch (e) {}
  if (want !== null && want === curLib && curTab === 'recommended') {
    var wb = bar.querySelector('button[data-lib="' + curLib + '"]');
    if (wb) { guard = Date.now() + 600; requestAnimationFrame(function () { open(wb); }); }
  }
  document.addEventListener('click', function (e) { if (!pop.hidden && !pop.contains(e.target) && !bar.contains(e.target)) close(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
  window.addEventListener('resize', function () { if (Date.now() > guard) close(); });
  window.addEventListener('scroll', function () { if (!pop.hidden && Date.now() > guard) close(); }, {passive: true});
})();
