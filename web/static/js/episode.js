// Página do episódio (36.1): fundo liga/desliga, slider do elenco, menu de episódios e marcar assistido.
(function () {
  function get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function put(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

  // 1º ícone da barra: liga/desliga o fundo (backdrop) do episódio
  var bg = document.querySelector('.mv-bg'), tb = document.getElementById('ep-bg');
  function setBg(on) {
    if (bg) bg.hidden = !on;
    if (!tb) return;
    tb.classList.toggle('on', on);
    tb.setAttribute('aria-pressed', on ? 'true' : 'false');
    tb.dataset.tip = T(on ? 'det.bg_hide' : 'det.bg_show');
  }
  if (tb) {
    setBg(get('sf.epbg') !== '0');
    tb.addEventListener('click', function () { var on = !!(bg && bg.hidden); setBg(on); put('sf.epbg', on ? '1' : '0'); });
  }

  // slider: só o tamanho dos avatares do elenco (não mexe no zoom dos pôsteres)
  var cr = document.getElementById('cast-range');
  if (cr) {
    var d = parseInt(get('sf.castd'), 10);
    cr.value = d >= 80 && d <= 200 ? d : 120;
    cr.addEventListener('input', function () {
      document.documentElement.style.setProperty('--cast-d', cr.value + 'px');
      put('sf.castd', cr.value);
      if (window.sfCarousel) document.querySelectorAll('.carousel').forEach(window.sfCarousel.init);
    });
  }

  // ☰: lista dos episódios da temporada
  var lb = document.getElementById('ep-list'), lm = document.getElementById('ep-menu'), caret = document.getElementById('ep-list-caret');
  function menu(open) {
    lm.hidden = !open;
    lb.setAttribute('aria-expanded', open ? 'true' : 'false');
    caret.querySelector('use').setAttribute('href', open ? '#i-chevron-up' : '#i-chevron-down');
    if (open) { var cur = lm.querySelector('.cur'); if (cur) cur.scrollIntoView({block: 'nearest'}); }
  }
  if (lb && lm) {
    lb.addEventListener('click', function (e) { e.stopPropagation(); menu(lm.hidden); });
    document.addEventListener('click', function (e) { if (!lm.hidden && !lm.contains(e.target)) menu(false); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !lm.hidden) menu(false); });
  }

  // ○ marcar como assistido / não assistido
  var mk = document.getElementById('mark');
  if (mk) mk.addEventListener('click', async function () {
    var r = await fetch('/progress/' + mk.dataset.kind + '/' + mk.dataset.id + '/watched', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({watched: mk.dataset.watched})
    });
    if (r.status === 401) { location.href = '/login'; return; }
    location.reload();
  });
})();
