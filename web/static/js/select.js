// Seleção múltipla (24.3): ○ marca o card; com seleção ativa o clique no card alterna; Shift+clique marca intervalo;
// Esc limpa; toque longo começa a seleção no celular. Cards com data-pick (id da mídia) — ver _card.html.
// Avisa a barra de seleção (24.4) pelo evento "sf:selection" ({detail: {ids}}) e expõe window.sfSelect.
(function () {
  var anchor = null, timer = null, longPressed = false, startX = 0, startY = 0;

  function cards() { return Array.prototype.slice.call(document.querySelectorAll('.pcard[data-pick]')); }
  function picked() { return cards().filter(function (c) { return c.classList.contains('picked'); }); }
  function ids() {  // o mesmo item pode estar em 2 fileiras do Início (32.10): conta uma vez
    var out = [];
    picked().forEach(function (c) { var n = parseInt(c.dataset.pick, 10); if (out.indexOf(n) < 0) out.push(n); });
    return out;
  }
  function active() { return document.body.classList.contains('sel-on'); }

  function paint(c, on) {
    cards().forEach(function (o) { if (o !== c && o.dataset.pick === c.dataset.pick) o.classList.toggle('picked', on); });
    c.classList.toggle('picked', on);
    var b = c.querySelector('.pcard-pick');
    if (b) { b.setAttribute('aria-pressed', on ? 'true' : 'false'); b.setAttribute('aria-label', on ? 'Desmarcar' : 'Selecionar'); }
  }
  function emit() {
    document.body.classList.toggle('sel-on', picked().length > 0);
    document.dispatchEvent(new CustomEvent('sf:selection', {detail: {ids: ids()}}));
  }
  function clear() {
    cards().forEach(function (c) { paint(c, false); });
    anchor = null;
    emit();
  }
  function toggle(c, range) {
    var list = cards();
    if (range && anchor && anchor !== c && document.contains(anchor)) {
      var a = list.indexOf(anchor), b = list.indexOf(c);
      if (a >= 0 && b >= 0) {
        for (var i = Math.min(a, b); i <= Math.max(a, b); i++) paint(list[i], true);
        anchor = c;
        emit();
        return;
      }
    }
    var on = !c.classList.contains('picked');
    paint(c, on);
    anchor = on ? c : anchor;
    emit();
  }
  function cardOf(e) { return e.target.closest ? e.target.closest('.pcard[data-pick]') : null; }

  document.addEventListener('click', function (e) {
    var c = cardOf(e);
    if (!c) return;
    if (longPressed) { longPressed = false; e.preventDefault(); e.stopPropagation(); return; }  // soltou o toque longo
    if (!e.target.closest('.pcard-pick') && !active()) return;  // sem seleção ativa o card se comporta como sempre
    e.preventDefault();
    e.stopPropagation();
    toggle(c, e.shiftKey);
  }, true);

  document.addEventListener('mousedown', function (e) {  // Shift+clique não pode selecionar texto
    if (e.shiftKey && cardOf(e)) e.preventDefault();
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && active() && !document.querySelector('.em-overlay:not([hidden])')) clear();
  });

  // celular: toque longo no card começa a seleção
  document.addEventListener('pointerdown', function (e) {
    if (e.pointerType !== 'touch' || e.target.closest('.pcard-pick')) return;
    var c = cardOf(e);
    if (!c) return;
    longPressed = false;
    startX = e.clientX; startY = e.clientY;
    clearTimeout(timer);
    timer = setTimeout(function () {
      longPressed = true;
      toggle(c, false);
      if (navigator.vibrate) navigator.vibrate(15);
    }, 500);
  }, true);
  ['pointerup', 'pointercancel'].forEach(function (t) {
    document.addEventListener(t, function () { clearTimeout(timer); }, true);
  });
  document.addEventListener('pointermove', function (e) {  // rolar a página cancela; tremida do dedo não
    if (Math.abs(e.clientX - startX) > 10 || Math.abs(e.clientY - startY) > 10) clearTimeout(timer);
  }, true);
  document.addEventListener('contextmenu', function (e) {
    if (cardOf(e) && (longPressed || active())) e.preventDefault();
  });

  window.sfSelect = {ids: ids, count: function () { return picked().length; }, clear: clear};
})();
