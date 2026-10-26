// Início (32.8): carrega as fileiras fantasma uma a uma por GET /home/row/<key>?html=1.
(function () {
  var ghosts = Array.prototype.slice.call(document.querySelectorAll('.carousel[data-ghost]'));
  if (!ghosts.length) return;

  function fill(c, html) {
    var t = c.querySelector('.carousel-track');
    t.innerHTML = html;
    c.removeAttribute('data-ghost');
    if (window.sfCarousel) window.sfCarousel.init(c);
  }

  function next() {
    var c = ghosts.shift();
    if (!c) return;
    fetch('/home/row/' + encodeURIComponent(c.dataset.row) + '?html=1', {credentials: 'same-origin', headers: {'Accept': 'application/json'}})
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; throw 0; }
        if (!r.ok) throw r.status;
        return r.json();
      })
      .then(function (j) { if (j && j.html && j.html.trim()) fill(c, j.html); else c.remove(); })
      .catch(function () { c.remove(); })  // fileira que sumiu (ou falhou): tira o fantasma
      .then(next);
  }
  next();
})();

// 60.7: o Continuar assistindo acompanha o que foi assistido em outro aparelho (TV/celular): ao voltar à aba/app, refaz a fileira
(function () {
  var hiddenAt = 0, busy = false;
  function row() { return document.querySelector('.carousel[data-row="continue"]'); }
  function refresh() {
    if (busy) return;
    busy = true;
    fetch('/home/row/continue?html=1&fresh=1', {credentials: 'same-origin', headers: {'Accept': 'application/json'}, cache: 'no-store'})
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; throw 0; }
        if (r.status === 404) return {html: ''};  // sem itens em andamento
        if (!r.ok) throw r.status;
        return r.json();
      })
      .then(function (j) {
        var c = row(), has = !!(j && j.html && j.html.trim());
        if (c && has) { c.querySelector('.carousel-track').innerHTML = j.html; if (window.sfCarousel) window.sfCarousel.init(c); }
        else if (c && !has) c.remove();
        else if (!c && has) location.reload();  // a fileira ainda não existia: monta o Início de novo
      })
      .catch(function () { })
      .then(function () { busy = false; });
  }
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) { hiddenAt = Date.now(); return; }
    if (hiddenAt && Date.now() - hiddenAt > 3000) refresh();
    hiddenAt = 0;
  });
  window.addEventListener('pageshow', function (e) { if (e.persisted) refresh(); });
})();
