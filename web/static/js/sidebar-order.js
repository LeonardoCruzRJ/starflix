/* 45.3: reordenar as bibliotecas da barra lateral arrastando; a ordem vai ao servidor (por usuário) e vale também para o app de TV e o do celular.
   56.2: vale também para a lista de bibliotecas do painel lateral novo (#tvd .tvd-libs). */
(function () {
  function init(nav, SEL) {
    if (!nav) return;
    var drag = null, before = '';

    function items() { return [].slice.call(nav.querySelectorAll(SEL)); }
    function ids() { return items().map(function (a) { return parseInt(a.getAttribute('href').split('/')[2], 10); }); }

    nav.addEventListener('dragstart', function (e) {
      var a = e.target.closest && e.target.closest(SEL);
      if (!a) return;
      drag = a; before = ids().join(',');
      e.dataTransfer.effectAllowed = 'move';
      try { e.dataTransfer.setData('text/plain', a.href); } catch (x) {}
      setTimeout(function () { a.classList.add('dragging'); }, 0);
    });
    nav.addEventListener('dragover', function (e) {
      if (!drag) return;
      var over = e.target.closest && e.target.closest(SEL);
      e.preventDefault();
      if (!over || over === drag) return;
      var r = over.getBoundingClientRect();
      if (e.clientY < r.top + r.height / 2) nav.insertBefore(drag, over); else over.after(drag);
    });
    nav.addEventListener('drop', function (e) { if (drag) e.preventDefault(); });
    nav.addEventListener('dragend', function () {
      if (!drag) return;
      drag.classList.remove('dragging');
      drag = null;
      var now = ids().join(',');
      if (now === before) return;
      fetch('/library/order', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ids: ids()})})
        .then(function (r) { if (!r.ok) throw new Error(); })
        .catch(function () { location.reload(); });  // falhou: volta à ordem do servidor
    });
  }
  init(document.querySelector('#sidebar .nav'), 'a.nav-item[href^="/library/"]');
  init(document.querySelector('#tvd .tvd-libs'), 'a.tvd-row[href^="/library/"]');
})();
