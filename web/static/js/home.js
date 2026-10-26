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
