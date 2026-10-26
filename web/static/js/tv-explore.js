/* 57.1: Explorar e Coleções da biblioteca (computador, >700 px) como a TV — o item em foco (mouse ou teclado, 350 ms parado)
   troca o fundo (sfHeroBg) e, ao abrir, o foco vai sozinho para o 1º item (fundo dele já aplicado). */
(function () {
  if (!document.body.classList.contains("tvh-exp") || !window.matchMedia("(min-width: 701px)").matches || !window.sfHeroBg) return;
  var grid = document.querySelector(".pgrid");
  if (!grid) { sfHeroBg.set(""); return; }
  var timer = null, current = "";

  function backdrop(card) {
    var id = card.dataset.collection, a = card.querySelector(".pcard-link"), href = a ? a.getAttribute("href") || "" : "", m;
    if (id) return "/collection-backdrop/" + id;
    if ((m = /^\/(?:movie|show)\/(\d+)/.exec(href))) return "/backdrop/" + m[1];
    if ((m = /^\/watch\/movie\/(\d+)/.exec(href))) return "/thumb/" + m[1];
    return null;
  }
  function apply(url) { if (url === current) return; current = url; sfHeroBg.set(url); }
  function pick(e) {
    var c = e.target.closest && e.target.closest(".pcard"), u = c && backdrop(c);
    if (!u || u === current) return;
    clearTimeout(timer);
    timer = setTimeout(function () { apply(u); }, 350);
  }
  grid.addEventListener("mouseover", function (e) {
    var c = e.target.closest && e.target.closest(".pcard"), t = c && c.querySelector(".pcard-title");
    if (t && document.activeElement !== t) t.focus({ preventScroll: true });  // um só realce, como o foco da TV
    pick(e);
  });
  grid.addEventListener("focusin", pick);

  // foco inicial: o 1º item da grade
  var first = grid.querySelector(".pcard:not(.pcard-ghost)"), u0 = first && backdrop(first), t0 = first && first.querySelector(".pcard-title");
  apply(u0 || "");
  if (t0) t0.focus({ preventScroll: true });
})();
