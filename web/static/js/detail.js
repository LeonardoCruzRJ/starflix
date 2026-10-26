// Páginas de detalhe (23.7/23.8): sinopse "Mais ⌄", botão de copiar link, Minha Lista e estrelas (23.16).
(function () {
  var o = document.getElementById('over'), b = document.getElementById('more');
  if (o && b) {
    if (o.scrollHeight > o.clientHeight + 2) b.hidden = false;
    b.addEventListener('click', function () {
      var open = o.classList.toggle('open');
      b.firstChild.nodeValue = T(open ? 'det.less' : 'det.more') + ' ';
      b.classList.toggle('open', open);
    });
  }
  var s = document.getElementById('share');
  if (s) s.addEventListener('click', function () {
    var url = location.href.split('#')[0], done = function () {
      s.dataset.tip = T('det.link_copied'); setTimeout(function () { s.dataset.tip = T('det.copy_link'); }, 1800);
    };
    window.sfCopy(url, done);
  });

  function post(url, method, body) {
    return fetch(url, {method: method, headers: {'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined})
      .then(function (r) { if (r.status === 401) { location.href = '/login'; throw 0; } return r.ok; });
  }
  var ml = document.getElementById('mylist');
  if (ml) ml.addEventListener('click', function () {
    var on = ml.dataset.on === '1';
    post('/list/' + ml.dataset.id, on ? 'DELETE' : 'POST').then(function (ok) {
      if (!ok) return;
      on = !on; ml.dataset.on = on ? '1' : '0'; ml.classList.toggle('on', on);
      ml.querySelector('use').setAttribute('href', on ? '#i-bookmark-fill' : '#i-bookmark');
      ml.dataset.tip = T('det.mylist.' + (on ? 'remove_' : 'add_') + ml.dataset.what);
    }).catch(function () {});
  });
  document.querySelectorAll('.mv-stars').forEach(function (box) {
    box.addEventListener('click', function (e) {
      var b = e.target.closest('button[data-v]');
      if (!b) return;
      var v = +b.dataset.v, cur = +box.dataset.value;
      if (v === cur) v = 0;  // clicar na nota atual limpa
      post('/stars/' + box.dataset.kind + '/' + box.dataset.id, 'POST', {stars: v}).then(function (ok) {
        if (!ok) return;
        box.dataset.value = v;
        box.querySelectorAll('.st').forEach(function (st, i) {
          st.classList.toggle('full', v >= 2 * (i + 1));
          st.classList.toggle('half', v === 2 * (i + 1) - 1);
        });
      }).catch(function () {});
    });
  });
})();

// Preferências de áudio/legenda (23.27): repassa ?audio=&sub= aos links de reprodução da página.
(function () {
  var a = document.getElementById('pf-audio'), s = document.getElementById('pf-sub');
  if (!a || !s) return;
  var links = Array.prototype.slice.call(document.querySelectorAll('a[href^="/watch/"], a[href*="/play"], a[href$="/random"]'));
  links.forEach(function (l) { l.dataset.h0 = l.getAttribute('href'); });
  function apply() {
    var q = [];
    if (a.value) q.push('audio=' + encodeURIComponent(a.value));
    if (s.value) q.push('sub=' + encodeURIComponent(s.value));
    links.forEach(function (l) {
      var h = l.dataset.h0;
      l.setAttribute('href', q.length ? h + (h.indexOf('?') < 0 ? '?' : '&') + q.join('&') : h);
    });
  }
  a.addEventListener('change', apply); s.addEventListener('change', apply);
})();
