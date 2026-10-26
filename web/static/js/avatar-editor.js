// Editor da foto do usuário (26.2, captura 62): escolher foto, zoom por slider, arrastar para ajustar o corte, remover.
// window.sfAvatarEditor.open(onSaved, urlAtual, arquivo?, opts?) — opts.url troca o endereço de envio (padrão /account/avatar); opts.onBlob(blob|null, previewUrl) devolve o recorte sem enviar (criação de perfil, 54.23)
// window.sfAvatarEditor.open(onSaved, urlAtual, arquivo?) -> abre o modal (com `arquivo` já abre no corte dessa foto); onSaved(url|null) é chamado após salvar/remover.
(function () {
  var V = 260, OUT = 512, el = null, st = null;

  function build() {
    el = document.createElement('div'); el.className = 'em-overlay'; el.hidden = true;
    el.innerHTML = '<div class="em-win em-small av-win" role="dialog" aria-modal="true"><div class="em-head"><span>' + T('acc.photo') + '</span>' +
      '<button type="button" class="em-x" aria-label="' + T('common.close') + '">✕</button></div><div class="em-pane av-pane">' +
      '<div class="av-edit"><div class="av-stage"><canvas width="' + V + '" height="' + V + '"></canvas><div class="av-mask"></div></div>' +
      '<div class="av-zoom"><span class="av-sm"></span><input type="range" min="1" max="3" step="0.01" value="1" aria-label="' + T('av.zoom') + '"><span class="av-lg"></span></div></div>' +
      '<div class="av-side"><button type="button" class="em-btn av-pick">' + T('av.pick') + '</button>' +
      '<p class="av-help">' + T('av.help', {link: '<a href="#" class="av-rm">' + T('av.remove') + '</a>'}) + '</p>' +
      '<div class="av-err"></div></div><input type="file" accept="image/jpeg,image/png,image/webp" hidden></div>' +
      '<div class="em-foot"><button type="button" class="em-btn em-cancel">' + T('common.cancel') + '</button><button type="button" class="em-btn em-save" disabled>' + T('common.save_changes') + '</button></div></div>';
    document.body.appendChild(el);
    var q = function (s) { return el.querySelector(s); };
    st = {c: q('canvas'), zoom: q('input[type=range]'), file: q('input[type=file]'), save: q('.em-save'), err: q('.av-err'),
          img: null, base: 1, s: 1, ox: 0, oy: 0, remove: false, dirty: false, cb: null, opts: {}, drag: null};
    q('.em-x').addEventListener('click', close); q('.em-cancel').addEventListener('click', close);
    el.addEventListener('mousedown', function (e) { if (e.target === el) close(); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !el.hidden) close(); });
    q('.av-pick').addEventListener('click', function () { st.file.click(); });
    st.file.addEventListener('change', function () { if (st.file.files[0]) pick(st.file.files[0]); });
    q('.av-rm').addEventListener('click', function (e) { e.preventDefault(); st.img = null; st.remove = true; mark(); draw(); });
    st.zoom.addEventListener('input', function () { zoomTo(parseFloat(st.zoom.value)); });
    st.c.addEventListener('pointerdown', function (e) { if (!st.img) return; st.drag = {x: e.clientX, y: e.clientY, ox: st.ox, oy: st.oy}; st.c.setPointerCapture(e.pointerId); });
    st.c.addEventListener('pointermove', function (e) { if (!st.drag) return; st.ox = st.drag.ox + e.clientX - st.drag.x; st.oy = st.drag.oy + e.clientY - st.drag.y; clamp(); draw(); mark(); });
    st.c.addEventListener('pointerup', function () { st.drag = null; });
    st.c.addEventListener('pointercancel', function () { st.drag = null; });
    st.save.addEventListener('click', save);
  }

  function mark() { st.dirty = true; st.save.disabled = false; }
  function close() { if (el) el.hidden = true; document.documentElement.classList.remove('em-open'); }
  function clamp() {
    if (!st.img) return;
    var w = st.img.width * st.s, h = st.img.height * st.s;
    st.ox = Math.min(0, Math.max(V - w, st.ox)); st.oy = Math.min(0, Math.max(V - h, st.oy));
  }
  function zoomTo(z) {
    if (!st.img) return;
    var cx = (V / 2 - st.ox) / st.s, cy = (V / 2 - st.oy) / st.s;  // mantém o centro
    st.s = st.base * z; st.ox = V / 2 - cx * st.s; st.oy = V / 2 - cy * st.s; clamp(); draw(); mark();
  }
  function draw() {
    var g = st.c.getContext('2d'); g.fillStyle = '#1a1a1a'; g.fillRect(0, 0, V, V);
    if (st.img) g.drawImage(st.img, st.ox, st.oy, st.img.width * st.s, st.img.height * st.s);
    else if (st.remove) { g.fillStyle = '#e5a00d'; g.fillRect(0, 0, V, V); }
  }
  function setImage(img, fresh) {
    st.img = img; st.remove = false; st.base = Math.max(V / img.width, V / img.height); st.s = st.base;
    st.ox = (V - img.width * st.s) / 2; st.oy = (V - img.height * st.s) / 2; st.zoom.value = 1; draw();
    if (fresh) mark();
  }
  function pick(file) {
    st.err.textContent = '';
    if (!/^image\/(jpeg|png|webp)$/.test(file.type)) { st.err.textContent = T('av.err.type'); return; }
    if (file.size > 10 * 1024 * 1024) { st.err.textContent = T('av.err.size'); return; }
    var img = new Image(), u = URL.createObjectURL(file);
    img.onload = function () { URL.revokeObjectURL(u); setImage(img, true); };
    img.onerror = function () { URL.revokeObjectURL(u); st.err.textContent = T('av.err.open'); };
    img.src = u;
  }
  async function save() {
    st.save.disabled = true; st.err.textContent = '';
    try {
      var r, j = {};
      if (st.img && st.dirty) {
        var o = document.createElement('canvas'); o.width = o.height = OUT;
        var k = OUT / V, g = o.getContext('2d');
        g.drawImage(st.img, st.ox * k, st.oy * k, st.img.width * st.s * k, st.img.height * st.s * k);
        var blob = await new Promise(function (ok) { o.toBlob(ok, 'image/jpeg', 0.92); });
        if (st.opts.onBlob) { var ob = st.opts.onBlob; close(); ob(blob, URL.createObjectURL(blob)); return; }
        var fd = new FormData(); fd.append('file', blob, 'avatar.jpg');
        r = await fetch(st.opts.url || '/account/avatar', {method: 'POST', body: fd});
      } else if (st.remove) {
        if (st.opts.onBlob) { var ob2 = st.opts.onBlob; close(); ob2(null, null); return; }
        r = await fetch(st.opts.url || '/account/avatar', {method: 'DELETE'});
      } else { close(); return; }
      if (r.status === 401) { location.href = '/login'; return; }
      try { j = await r.json(); } catch (e) {}
      if (!r.ok) { st.err.textContent = SF_I18N.msg(j) || T('av.err.save'); st.save.disabled = false; return; }
      var cb = st.cb; close();
      if (cb) cb(st.remove ? null : j.url); else location.reload();
    } catch (e) { st.err.textContent = T('common.network_error'); st.save.disabled = false; }
  }

  function open(cb, current, file, opts) {
    if (!el) build();
    st.cb = cb; st.opts = opts || {}; st.img = null; st.remove = false; st.dirty = false; st.save.disabled = true; st.err.textContent = ''; st.file.value = ''; st.zoom.value = 1;
    draw(); el.hidden = false; document.documentElement.classList.add('em-open');
    if (file) { pick(file); return; }  // celular: a foto já veio do menu "Alterar Imagem do Perfil"
    if (current) { var im = new Image(); im.onload = function () { if (!st.dirty && !st.remove) setImage(im, false); }; im.src = current; }
  }
  window.sfAvatarEditor = {open: open};
})();
