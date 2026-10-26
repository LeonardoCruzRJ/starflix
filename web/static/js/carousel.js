// Carrossel com setas e slider de zoom dos pôsteres (23.4).
(function () {
  var ZMIN = 120, ZMAX = 200, KEY = 'sf.zoom';
  var root = document.documentElement;

  function applyZoom(z) {
    root.style.setProperty('--card-w', z + 'px');
    root.style.setProperty('--ep-w', Math.round(z * 2.2) + 'px');
  }
  function savedZoom() {
    try { var z = parseInt(localStorage.getItem(KEY), 10); if (z >= ZMIN && z <= ZMAX) return z; } catch (e) {}
    return ZMIN;
  }

  document.querySelectorAll('.zoom-range').forEach(function (r) {
    r.min = ZMIN; r.max = ZMAX;
    r.value = savedZoom();
    r.addEventListener('input', function () {
      var z = parseInt(r.value, 10);
      applyZoom(z);
      try { localStorage.setItem(KEY, String(z)); } catch (e) {}
      document.querySelectorAll('.zoom-range').forEach(function (o) { if (o !== r) o.value = z; });
      document.querySelectorAll('.carousel').forEach(update);
    });
  });

  function update(c) {
    var t = c.querySelector('.carousel-track');
    var prev = c.querySelector('[data-dir="-1"]'), next = c.querySelector('[data-dir="1"]');
    var over = t.scrollWidth - t.clientWidth > 2;
    c.querySelector('.carousel-arrows').hidden = !over;
    prev.disabled = t.scrollLeft <= 2;
    next.disabled = t.scrollLeft >= t.scrollWidth - t.clientWidth - 2;
  }

  function init(c) {
    var t = c.querySelector('.carousel-track');
    if (!c._sf) {  // setas e rolagem ligadas uma única vez (as fileiras do Início chegam depois, 32.8)
      c._sf = true;
      c.querySelectorAll('.carousel-btn').forEach(function (b) {
        b.addEventListener('click', function () {
          t.scrollBy({left: parseInt(b.dataset.dir, 10) * t.clientWidth * 0.9, behavior: 'smooth'});
        });
      });
      t.addEventListener('scroll', function () { update(c); }, {passive: true});
    }
    update(c);
    t.querySelectorAll('img').forEach(function (i) { i.addEventListener('load', function () { update(c); }); });
  }
  window.sfCarousel = {init: init};
  document.querySelectorAll('.carousel').forEach(init);
  window.addEventListener('resize', function () { document.querySelectorAll('.carousel').forEach(update); });
  window.addEventListener('load', function () { document.querySelectorAll('.carousel').forEach(update); });
})();
