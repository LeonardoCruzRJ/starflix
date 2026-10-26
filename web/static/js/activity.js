// 53.3: tooltip do ícone Painel com o que o servidor está fazendo agora (atualiza sozinho; fecha ao sair com o mouse)
(function () {
  var btn = document.getElementById('act-btn');
  if (!btn || !window.matchMedia('(hover: hover)').matches) return;
  var tip = document.createElement('div'); tip.className = 'act-tip'; tip.hidden = true; tip.setAttribute('role', 'status');
  btn.style.position = 'relative'; btn.appendChild(tip);
  var timer = null, on = false, seq = 0;
  function dur(s) { return SF_I18N.fmt.minsec(s); }
  function paint(items) {
    tip.innerHTML = '';
    var h = document.createElement('div'); h.className = 'act-h'; h.textContent = T('act.title'); tip.appendChild(h);
    if (!items.length) { var e = document.createElement('div'); e.className = 'act-i act-none'; e.textContent = T('act.none'); tip.appendChild(e); return; }
    items.forEach(function (it) {
      var r = document.createElement('div'); r.className = 'act-i';
      var d = document.createElement('span'); d.className = 'act-dot';
      var t = document.createElement('span'); t.className = 'act-t'; t.textContent = it.text;
      r.appendChild(d); r.appendChild(t);
      var x = it.pct != null ? it.pct + '%' : (it.secs != null ? dur(it.secs) : '');
      if (x) { var s = document.createElement('span'); s.className = 'act-s'; s.textContent = x; r.appendChild(s); }
      tip.appendChild(r);
    });
  }
  async function tick() {
    if (!on) return;
    var my = ++seq;
    try {
      var r = await fetch('/admin/activity', {cache: 'no-store'});
      if (r.ok && on && my === seq) paint((await r.json()).items || []);
    } catch (e) {}
    if (on) timer = setTimeout(tick, 1000);
  }
  btn.addEventListener('mouseenter', function () { on = true; tip.hidden = false; tip.innerHTML = ''; var h0 = document.createElement('div'); h0.className = 'act-h'; h0.textContent = T('act.title'); var l0 = document.createElement('div'); l0.className = 'act-i act-none'; l0.textContent = T('common.loading'); tip.appendChild(h0); tip.appendChild(l0); tick(); });
  btn.addEventListener('mouseleave', function () { on = false; seq++; clearTimeout(timer); tip.hidden = true; });
})();
