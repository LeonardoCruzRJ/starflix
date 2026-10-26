/* 56.2: painel lateral do app da TV — abre com o mouse em cima, o foco ou o botão ⋯ da pílula; fecha ao sair, com Esc ou clicando fora;
   ↑/↓ andam entre as linhas (como o D-pad), → abre/← fecha. */
(function () {
  var box = document.getElementById("tvd");
  if (!box) return;
  var panel = box.querySelector(".tvd-panel");
  var timer = null;
  var prof = document.getElementById("tvd-prof"), um = document.getElementById("tvd-umenu");  // popup do usuário (nome e avatar)

  function closeUm() { if (um) { um.hidden = true; if (prof) prof.setAttribute("aria-expanded", "false"); } }

  function open() { clearTimeout(timer); box.classList.add("open"); }
  function close() {
    clearTimeout(timer);
    box.classList.remove("open");
    closeUm();
    if (panel.contains(document.activeElement)) document.activeElement.blur();
  }
  function later() { clearTimeout(timer); timer = setTimeout(close, 250); }

  box.addEventListener("mouseenter", open);
  box.addEventListener("mouseleave", later);
  box.addEventListener("focusin", open);
  box.addEventListener("focusout", function (e) { if (!box.contains(e.relatedTarget)) later(); });
  document.getElementById("tvd-pill-more").addEventListener("click", function () { open(); });
  if (prof && um) prof.addEventListener("click", function () {
    if (!um.hidden) { closeUm(); return; }
    var r = prof.getBoundingClientRect(), pr = panel.getBoundingClientRect();
    um.hidden = false;
    um.style.left = (pr.right + 8) + "px";
    um.style.top = Math.max(8, Math.min(r.top, window.innerHeight - um.offsetHeight - 8)) + "px";
    prof.setAttribute("aria-expanded", "true");
  });
  document.addEventListener("click", function (e) { if (!box.contains(e.target)) close(); });

  function rows() { return [].slice.call(panel.querySelectorAll(".tvd-row")).filter(function (r) { return r.offsetParent !== null; }); }
  box.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { if (um && !um.hidden) { closeUm(); if (prof) prof.focus(); return; } close(); return; }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    var r = rows(), i = r.indexOf(document.activeElement);
    if (!r.length) return;
    e.preventDefault();
    i = e.key === "ArrowDown" ? (i + 1) % r.length : (i <= 0 ? r.length - 1 : i - 1);
    r[i].focus();
  });
})();
