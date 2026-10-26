/* 56.8: detalhe de filme e série no visual da TV — fundo hero-bg com o backdrop e logo no lugar do título. 57.17: também no celular (≤700 px) nas páginas de item (`tvh-md`); busca e Minha Lista seguem só no computador. */
(function () {
  var wide = window.matchMedia("(min-width: 701px)").matches;
  if (!wide && !document.body.classList.contains("tvh-md")) return;
  if (wide && document.body.classList.contains("tvh-sr") && window.sfHeroBg) {  // 56.10: busca e Minha Lista — fundo da TV; o cartão em foco troca o backdrop
    sfHeroBg.set("");
    var t = null;
    var pick = function (e) {
      var c = e.target.closest && e.target.closest(".pcard"), a = c && c.querySelector(".pcard-link"), mm = a && /^\/(?:movie|show)\/(\d+)/.exec(a.getAttribute("href") || "");
      if (!mm) return;
      clearTimeout(t);
      t = setTimeout(function () { sfHeroBg.set("/backdrop/" + mm[1]); }, 350);
    };
    document.addEventListener("mouseover", pick);
    document.addEventListener("focusin", pick);
    return;
  }
  var bg = document.querySelector(".mv-bg"), m = bg && /url\(['"]?([^'")]+)/.exec(bg.getAttribute("style") || "");
  if (m && window.sfHeroBg) sfHeroBg.set(m[1]);
  var tb = document.getElementById("ep-bg");  // episódio: o botão de fundo liga/desliga o hero-bg (episode.js grava sf.epbg depois deste clique)
  if (tb && m && window.sfHeroBg) {
    try { if (localStorage.getItem("sf.epbg") === "0") sfHeroBg.clear(); } catch (x) {}
    tb.addEventListener("click", function () {
      var wasOn = true; try { wasOn = localStorage.getItem("sf.epbg") !== "0"; } catch (x) {}
      if (wasOn) sfHeroBg.clear(); else sfHeroBg.set(m[1]);
    });
  }
  // temporada (57.21): foco (computador) e rolagem (celular) no episódio em andamento; se o último com progresso já foi todo assistido, o seguinte; sem progresso, o 1º
  var grid = document.querySelector(".pgrid-wide");
  if (grid && document.querySelector(".mv-pills")) {
    var cards = grid.querySelectorAll(".pcard"), last = -1, idx = 0;
    var seen = function (c) { return !!c.querySelector(".pcard-seen"); };
    var part = function (c) { return !seen(c) && !!c.querySelector(".pcard-bar"); };
    for (var i = 0; i < cards.length; i++) { if (seen(cards[i]) || part(cards[i])) last = i; }
    if (last >= 0) idx = part(cards[last]) ? last : (last + 1 < cards.length ? last + 1 : 0);
    var f = cards[idx], a = f && f.querySelector(".pcard-title");
    var back = false; try { back = performance.getEntriesByType("navigation")[0].type === "back_forward"; } catch (x) {}
    if (a) {
      if (wide) a.focus({ preventScroll: true });
      if (idx > 0 && (wide || !back)) f.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }
  var lg = document.getElementById("md-logo"), tt = document.getElementById("md-title");
  if (!lg || !tt) return;
  lg.onload = function () { lg.hidden = false; tt.hidden = true; };
  lg.onerror = function () { lg.remove(); };
  if (lg.complete && lg.naturalWidth) lg.onload();
})();
