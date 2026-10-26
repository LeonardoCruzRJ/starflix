/* 56.6: Explorar da biblioteca (computador) — índice alfabético na borda direita
   (só quando ordenado por título; passar/clicar na letra rola até o 1º item; a letra atual fica circulada). */
(function () {
  if (!window.matchMedia("(min-width: 701px)").matches) return;
  var bar = document.getElementById("lib-bar"), grid = document.querySelector(".pgrid");
  if (!bar || !grid || bar.dataset.sort !== "title") return;
  function letter(t) {
    var c = String(t || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim().charAt(0).toUpperCase();
    return /[A-Z]/.test(c) ? c : "#";
  }
  var first = {}, order = [];
  grid.querySelectorAll(".pcard:not([data-collection])").forEach(function (c) {
    var t = c.querySelector(".pcard-title"), l = letter(t && t.textContent);
    if (!first[l]) { first[l] = c; order.push(l); }
  });
  if (order.length < 2) return;
  var nav = document.createElement("nav");
  nav.className = "lib-alpha";
  nav.setAttribute("aria-label", T("lib.alpha"));
  order.forEach(function (l) {
    var b = document.createElement("button");
    b.type = "button"; b.textContent = l; b.dataset.l = l;
    b.addEventListener("click", go); b.addEventListener("mouseenter", go);
    nav.appendChild(b);
  });
  document.body.appendChild(nav);
  var last = "";
  function go(e) {
    var l = e.currentTarget.dataset.l;
    if (l === last && e.type === "mouseenter") return;
    last = l;
    first[l].scrollIntoView({ block: "start", behavior: "smooth" });
  }
  var tick = false;
  function mark() {
    tick = false;
    var cur = order[0];
    order.forEach(function (l) { if (first[l].getBoundingClientRect().top <= 150) cur = l; });
    nav.querySelectorAll("button").forEach(function (b) { b.classList.toggle("on", b.dataset.l === cur); });
  }
  function onScroll() { if (!tick) { tick = true; requestAnimationFrame(mark); } }
  window.addEventListener("scroll", onScroll, { passive: true, capture: true });
  mark();
})();
