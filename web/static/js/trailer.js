// 64.3: trailer mudo no destaque (Início e Recomendado). Um vídeo por vez, sem pré-carregar nada e só quando o perfil deixa:
// body[data-hero-trailer] = auto (computador sim, tela de toque não) | on | off. Respeita prefers-reduced-motion e economia de dados.
// 404 (item sem trailer ou clipe ainda não gerado) vira "sem trailer" por 10 min, sem repetir o pedido.
(function () {
  var cur = null, dead = {};
  function mode() { return document.body.getAttribute('data-hero-trailer') || 'auto'; }
  function allowed() {
    var m = mode();
    if (m === 'off') return false;
    try {
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return false;
      if (navigator.connection && navigator.connection.saveData) return false;
      if (m === 'auto' && window.matchMedia('(pointer: coarse)').matches) return false;
    } catch (e) {}
    return true;
  }
  function neg(k) {
    var t = dead[k] || 0;
    try { t = Math.max(t, +sessionStorage.getItem('sf.tr0.' + k) || 0); } catch (e) {}
    return !!t && Date.now() - t < 600000;
  }
  function mark(k) { dead[k] = Date.now(); try { sessionStorage.setItem('sf.tr0.' + k, String(dead[k])); } catch (e) {} }
  function stop() {
    var c = cur;
    if (!c) return;
    cur = null;
    if (c.wait) clearTimeout(c.wait);
    var v = c.v;
    try { v.pause(); v.removeAttribute('src'); v.load(); } catch (e) {}
    if (v.parentNode) v.parentNode.removeChild(v);
  }
  // host = onde o <video> entra; o = {cls, before (nó do host), max (segundos)}. Devolve true se começou a tentar.
  function play(host, kind, id, o) {
    o = o || {};
    var key = kind + '.' + id;
    if (!host || !allowed() || neg(key)) return false;
    stop();
    var v = document.createElement('video'), me = { v: v, wait: null };
    v.className = o.cls || '';
    v.muted = true; v.defaultMuted = true; v.playsInline = true; v.preload = 'none'; v.loop = false; v.tabIndex = -1;
    v.setAttribute('muted', ''); v.setAttribute('playsinline', ''); v.setAttribute('aria-hidden', 'true');
    v.disablePictureInPicture = true; v.setAttribute('disableremoteplayback', '');
    cur = me;
    me.wait = setTimeout(function () { if (cur === me && !v.classList.contains('on')) stop(); }, 8000);
    v.addEventListener('playing', function () { if (cur === me) v.classList.add('on'); });
    v.addEventListener('ended', function () { if (cur === me) stop(); });
    v.addEventListener('error', function () { if (cur === me) { mark(key); stop(); } });
    v.addEventListener('timeupdate', function () { if (cur === me && o.max && v.currentTime >= o.max) stop(); });
    v.src = '/trailer/' + kind + '/' + id;
    if (o.before && o.before.parentNode === host) host.insertBefore(v, o.before); else host.appendChild(v);
    var p = v.play();
    if (p && p.catch) p.catch(function () { if (cur === me) stop(); });
    return true;
  }
  document.addEventListener('visibilitychange', function () { if (document.hidden) stop(); });
  window.addEventListener('pagehide', stop);
  window.sfTrailer = { allowed: allowed, play: play, stop: stop, active: function () { return !!cur; } };
})();
