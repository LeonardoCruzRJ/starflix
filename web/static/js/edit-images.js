// Abas de imagem (23.20): Pôster, Plano de fundo, Logo, Arte Quadrada (stills no episódio).
(window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () {
  var CUR = {
    movie: {poster: '/poster/', backdrop: '/backdrop/', logo: '/logo/', square: '/square/'},
    show: {poster: '/poster/', backdrop: '/backdrop/', logo: '/logo/', square: '/square/'},
    collection: {poster: '/collection-poster/', backdrop: '/collection-backdrop/', logo: '/collection-logo/', square: '/collection-square/'}
  };
  var COLS = {poster: 3, backdrop: 2, logo: 3, square: 3};
  function curUrl(d, slot) {
    if (d.kind === 'video') return '/thumb/' + d.ref + '?t=' + Date.now();  // 34.6: frame do vídeo ou imagem escolhida
    if (!d.images[slot]) return null;
    var t = '?t=' + Date.now();
    if (d.kind === 'season') { var p = d.ref.split('-'); return slot === 'poster' ? '/season-poster/' + p[0] + '/' + p[1] + t : null; }
    if (d.kind === 'episode') return '/still/' + d.ref + t;
    return CUR[d.kind][slot] + d.ref + t;
  }
  function mk(slot) {
    return {render: function (pane, data, api) {
      var wide = data.kind === 'episode' || data.kind === 'video';
      var strip = document.createElement('div'), grid = document.createElement('div'), msg = document.createElement('div'),
          file = document.createElement('input');
      strip.className = 'em-strip';
      var a1 = document.createElement('a'), a2 = document.createElement('a');
      a1.href = '#'; a1.dataset.a = 'file'; a1.textContent = T('ei.choose'); a2.href = '#'; a2.dataset.a = 'url'; a2.textContent = T('ei.url');
      strip.appendChild(a1); strip.appendChild(document.createTextNode(' · ' + T('ei.drop') + ' · ')); strip.appendChild(a2);
      file.type = 'file'; file.accept = 'image/jpeg,image/png,image/webp'; file.hidden = true;
      grid.className = 'em-grid em-grid-' + (wide ? 'w' : COLS[slot]) + (slot === 'logo' ? ' em-grid-logo' : '');
      msg.className = 'em-msg';
      pane.appendChild(strip); pane.appendChild(file); pane.appendChild(msg); pane.appendChild(grid);
      if (slot === 'logo' || data.kind === 'video') {
        var clr = document.createElement('a'); clr.href = '#'; clr.className = 'em-clear'; clr.textContent = data.kind === 'video' ? T('ei.back_frame') : T('ei.unmark');
        clr.addEventListener('click', function (e) { e.preventDefault(); send({clear: '1'}); });
        pane.insertBefore(clr, grid);
      }
      var base = '/admin/item/' + data.kind + '/' + encodeURIComponent(data.ref);

      function tile(src, sel, onclick) {
        var t = document.createElement('div'); t.className = 'em-tile' + (sel ? ' on' : '');
        var i = document.createElement('img'); i.src = src; i.loading = 'lazy'; i.alt = ''; i.onerror = function () { t.remove(); };
        t.appendChild(i); t.insertAdjacentHTML('beforeend', '<span class="em-ck">✓</span>');
        if (onclick) t.addEventListener('click', onclick);
        return t;
      }
      async function send(fields, f) {
        var fd = new FormData();
        Object.keys(fields).forEach(function (k) { fd.append(k, fields[k]); });
        if (f) fd.append('file', f);
        msg.textContent = T('common.apply');
        try {
          var r = await fetch(base + '/image/' + slot, {method: 'POST', body: fd}), j = {};
          try { j = await r.json(); } catch (e) {}
          if (!r.ok) { msg.textContent = SF_I18N.msg(j) || T('common.error'); return; }
          msg.textContent = '';
          data.images[slot] = j.name || null;
          api.reload = true;                     // fechar o modal recarrega a página
          Array.prototype.forEach.call(grid.children, function (c) { c.classList.remove('on'); });
          if (j.name) { var c = curUrl(data, slot); grid.insertBefore(tile(c, true), grid.firstChild); }
        } catch (e) { msg.textContent = T('common.network_error'); }
      }
      strip.addEventListener('click', function (e) {
        var a = e.target.closest('a'); if (!a) return; e.preventDefault();
        if (a.dataset.a === 'file') file.click();
        else { var u = prompt(T('ei.prompt')); if (u) send({url: u}); }
      });
      file.addEventListener('change', function () { if (file.files[0]) send({}, file.files[0]); file.value = ''; });
      pane.addEventListener('dragover', function (e) { e.preventDefault(); });
      pane.addEventListener('drop', function (e) {
        e.preventDefault();
        var f = e.dataTransfer.files && e.dataTransfer.files[0], u = e.dataTransfer.getData('text/uri-list');
        if (f) send({}, f); else if (u && /^https?:/.test(u)) send({url: u.split('\n')[0]});
      });
      var c0 = curUrl(data, slot);
      if (c0) grid.appendChild(tile(c0, true));
      fetch(base + '/images/' + slot).then(function (r) { return r.json(); }).then(function (j) {
        (j.items || []).forEach(function (it) {
          grid.appendChild(tile(it.thumb, false, function () { send(it.media ? {media: it.media} : {path: it.path}); }));
        });
        if (j.error) msg.textContent = SF_I18N.msg(j);
      }).catch(function () {});
    }};
  }
  ['poster', 'backdrop', 'logo', 'square'].forEach(function (s) { window.sfEditTabs[s] = mk(s); });
});
