// 54.2/54.13: destaque do celular — faixa com rolagem por toque (snap), pontos, troca automática e rotação infinita
// (clones do último antes do 1º e do 1º depois do último; ao parar num clone, salta sem animação para o item de verdade)
(function () {
  var box = document.getElementById('m-hero');
  if (!box) return;
  var tr = box.querySelector('.m-hero-track'), dots = box.querySelectorAll('.m-hero-dots i'), n = dots.length, cur = 0, timer = null, touching = false;
  var slides = tr ? tr.querySelectorAll('.m-hero-slide') : [];
  if (!tr || !slides.length) return;
  n = slides.length;
  var loop = n > 1;
  if (loop) {
    var a = slides[n - 1].cloneNode(true), b = slides[0].cloneNode(true);
    a.setAttribute('aria-hidden', 'true'); b.setAttribute('aria-hidden', 'true');
    a.querySelectorAll('a').forEach(function (x) { x.tabIndex = -1; }); b.querySelectorAll('a').forEach(function (x) { x.tabIndex = -1; });
    tr.insertBefore(a, slides[0]);
    tr.appendChild(b);
  }
  function w() { return Math.max(1, tr.clientWidth); }
  function pos() { return Math.round(tr.scrollLeft / w()); }               // posição na faixa (com clones)
  function real(p) { return loop ? ((p - 1) % n + n) % n : p; }            // índice do item de verdade
  function mark(i) { cur = i; for (var k = 0; k < dots.length; k++) dots[k].classList.toggle('on', k === i); }
  function jump(p) {                                                       // vai para p sem animação e sem o snap atrapalhar
    tr.style.scrollSnapType = 'none';
    tr.scrollLeft = p * w();
    requestAnimationFrame(function () { requestAnimationFrame(function () { tr.style.scrollSnapType = ''; }); });
  }
  function fix() {                                                         // parou num clone: troca pelo item de verdade
    if (!loop) return;
    var p = pos();
    if (p <= 0) jump(n); else if (p >= n + 1) jump(1);
  }
  function go(p) { tr.scrollTo({left: p * w(), behavior: 'smooth'}); }
  var raf = 0, settle = 0;
  tr.addEventListener('scroll', function () {
    clearTimeout(settle); settle = setTimeout(fix, 90);
    if (raf) return;
    raf = requestAnimationFrame(function () { raf = 0; mark(real(pos())); });
  }, {passive: true});
  if ('onscrollend' in window) tr.addEventListener('scrollend', fix);
  function start() { stop(); if (n > 1) timer = setInterval(function () { if (!touching && !document.hidden) go(pos() + 1); }, 6000); }
  function stop() { if (timer) { clearInterval(timer); timer = null; } }
  tr.addEventListener('touchstart', function () { touching = true; fix(); }, {passive: true});
  tr.addEventListener('touchend', function () { touching = false; start(); }, {passive: true});
  window.addEventListener('resize', function () { jump(loop ? real(pos()) + 1 : pos()); });
  if (loop) jump(1);
  mark(0); start();
})();
