// Menu "⋯" estilo Plex (23.10): botões [data-menu='[...]'] das páginas de detalhe e o ⋮ dos cards.
// Itens: {l: rótulo, h: url} navega · {l, c: "#seletor"} clica no elemento · {l, copy: url} copia o link · {sep: 1} separador · {l, sub: [...]} abre submenu (25.1).
(function () {
  window.sfCopy = function (url, done) {
    if (navigator.clipboard && window.isSecureContext) { navigator.clipboard.writeText(url).then(done); return; }
    var t = document.createElement('textarea'); t.value = url; t.style.position = 'fixed'; t.style.opacity = '0';
    document.body.appendChild(t); t.select();
    try { if (document.execCommand('copy') && done) done(); } catch (e) {}
    document.body.removeChild(t);
  };

  var menu = null, trigger = null, subMenu = null, subOwner = null, matched = null;
  if (window.sfAdmin) {  // 35.2: ids com correspondência; sem a lista (ainda), o item aparece
    fetch('/admin/matched').then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { if (j) matched = new Set(j.ids); }).catch(function () {});
  }
  function closeSub() {
    if (subMenu) { subMenu.remove(); subMenu = null; }
    if (subOwner) { subOwner.classList.remove('open'); subOwner = null; }
  }
  function close() {
    closeSub();
    if (menu) { menu.remove(); menu = null; }
    if (trigger) { trigger.classList.remove('open'); trigger = null; }
  }

  function run(it) {
    close();
    if (it.fn) { it.fn(); return; }
    if (it.h) { location.href = it.h; return; }
    if (it.el) { it.el.click(); return; }
    if (it.c) { var e = document.querySelector(it.c); if (e) e.click(); return; }
    if (it.act) { if (window.sfItemAction) window.sfItemAction(it); return; }
    if (it.copy !== undefined) window.sfCopy(it.copy || location.href.split('#')[0]);
  }

  var menuCls = '';
  function open(btn, items, kb, cls) {
    menuCls = cls || '';
    close();
    if (!items.length) return;
    trigger = btn; btn.classList.add('open');
    menu = document.createElement('div');
    menu.className = 'ctx-menu' + (menuCls ? ' ' + menuCls : ''); menu.setAttribute('role', 'menu');
    items.forEach(function (it) {
      if (it.sep) { var s = document.createElement('div'); s.className = 'ctx-sep'; menu.appendChild(s); return; }
      var b = document.createElement('button');
      b.type = 'button'; b.setAttribute('role', 'menuitem'); b.textContent = it.l;
      if (it.on) b.classList.add('on');
      if (it.r) {  // texto à direita (ex.: sentido da ordenação)
        b.classList.add('has-r');
        var rr = document.createElement('span'); rr.className = 'ctx-r'; rr.textContent = it.r; b.appendChild(rr);
      } else if (it.on) {  // ✓ do item escolhido
        var ck = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); ck.setAttribute('class', 'ic ic-sm ctx-check');
        ck.innerHTML = '<use href="#i-check"/>'; b.appendChild(ck);
      }
      if (it.off) { b.disabled = true; b.title = typeof it.off === 'string' ? it.off : T('mn.na'); }
      if (it.sub && it.sub.length) {
        b.classList.add('has-sub'); b.setAttribute('aria-haspopup', 'true');
        var ar = document.createElement('span'); ar.className = 'ctx-arrow'; ar.textContent = '\u25B6'; b.appendChild(ar);
        b.addEventListener('click', function (e) { e.stopPropagation(); toggleSub(b, it.sub); });
        b.addEventListener('mouseenter', function () { if (canHover()) openSub(b, it.sub); });
      } else {
        b.addEventListener('mouseenter', function () { if (canHover()) closeSub(); });
        b.addEventListener('click', function (e) { e.stopPropagation(); run(it); });
      }
      menu.appendChild(b);
    });
    document.body.appendChild(menu);
    var r = btn.getBoundingClientRect(), w = menu.offsetWidth, h = menu.offsetHeight;
    var left = Math.min(Math.max(8, menuCls.indexOf('ctx-right') >= 0 ? r.right - w : r.left), window.innerWidth - w - 8);
    var top = r.bottom + 4;
    if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 4);
    menu.style.left = left + 'px'; menu.style.top = top + 'px';
    if (kb) { var f = menu.querySelector('button'); if (f) f.focus(); }
  }

  // Submenu (25.1): ao lado no desktop (hover/clique); abaixo do item, em linha, no toque/celular.
  function canHover() { return window.matchMedia('(hover: hover)').matches && window.innerWidth > 600; }
  function toggleSub(btn, items) { if (subOwner === btn) { closeSub(); return; } openSub(btn, items); }
  function openSub(btn, items) {
    if (subOwner === btn) return;
    closeSub();
    subOwner = btn; btn.classList.add('open');
    subMenu = document.createElement('div');
    subMenu.className = 'ctx-menu ctx-sub' + (menuCls ? ' ' + menuCls : ''); subMenu.setAttribute('role', 'menu');
    items.forEach(function (it) {
      if (it.sep) { var s = document.createElement('div'); s.className = 'ctx-sep'; subMenu.appendChild(s); return; }
      var b = document.createElement('button');
      b.type = 'button'; b.setAttribute('role', 'menuitem'); b.textContent = it.l;
      b.addEventListener('click', function (e) { e.stopPropagation(); run(it); });
      subMenu.appendChild(b);
    });
    document.body.appendChild(subMenu);
    var r = btn.getBoundingClientRect(), w = subMenu.offsetWidth, h = subMenu.offsetHeight, left, top;
    if (canHover()) {
      left = r.right + 2;
      if (left + w > window.innerWidth - 8) left = Math.max(8, r.left - w - 2);  // sem espaço à direita: abre à esquerda
      top = r.top - 8;
    } else {
      left = r.left; top = r.bottom; subMenu.style.width = r.width + 'px'; subMenu.classList.add('ctx-sub-inline');
    }
    if (top + h > window.innerHeight - 8) top = Math.max(8, window.innerHeight - h - 8);
    subMenu.style.left = left + 'px'; subMenu.style.top = top + 'px';
  }

  // Remover da coleção (24.8): só admin, na página da coleção (window.sfCollection = id da coleção)
  window.sfRemoveFromCollection = async function (ids) {
    for (var i = 0; i < ids.length; i++) {
      var r = await fetch('/admin/collections/' + window.sfCollection + '/items/' + ids[i], {method: 'DELETE'});
      if (r.status === 401) { location.href = '/login'; return; }
    }
    location.reload();
  };

  window.sfMenuAt = function (btn, items, kb, cls) { if (trigger === btn) { close(); return; } open(btn, items, kb, cls); };

  function cardItems(card) {
    var a = card.querySelector('.pcard-title'), href = a ? a.getAttribute('href') : '', items = [], m;
    if ((m = href.match(/^\/show\/(\d+)$/))) items.push({l: T('lib.shuffle'), h: '/show/' + m[1] + '/random'});
    else if ((m = href.match(/^\/show\/(\d+)\/season\/(\d+)$/))) items.push({l: T('lib.shuffle'), h: href + '/play?random=1'});
    var sel = card.querySelector('.pcard-sel');
    if (sel) items.push({l: sel.dataset.watched === '1' ? T('card.mark_watched') : T('card.mark_unwatched'), el: sel});
    if ((m = href.match(/^\/movie\/(\d+)$/))) items.push({l: T('det.save_file'), h: '/download/movie/' + m[1]});
    if (href && href.charAt(0) === '/') {
      if (items.length) items.push({sep: 1});
      items.push({l: T('det.copy_link'), copy: location.origin + href});
    }
    if (window.sfAdmin && window.sfCollection && card.dataset.pick) {
      if (items.length) items.push({sep: 1});
      items.push({l: T('mn.remove_col'), fn: function () { window.sfRemoveFromCollection([parseInt(card.dataset.pick, 10)]); }});
    }
    var k = window.sfAdmin && window.sfCardItem ? window.sfCardItem(card) : null;
    if (k) {
      var nm = a ? a.textContent : '';
      if (k[0] === 'movie' || k[0] === 'show' || k[0] === 'video') return arrange(items, window.sfAdminItems(k[0], k[1], nm));
      if (items.length) items.push({sep: 1});
      items = items.concat(window.sfAdminItems(k[0], k[1], nm));
    }
    return items;
  }

  // Itens admin do menu (23.25): usados nos cards e nas páginas de detalhe
  window.sfAdminItems = function (kind, ref, name) {
    var b = {kind: kind, ref: ref, name: name}, out = [];
    function it(l, act) { var o = {l: l, act: act}; for (var x in b) o[x] = b[x]; return o; }
    if (kind === 'movie' || kind === 'show') {  // ordem das capturas 52 e 54 (25.3)
      out.push({l: T('mn.add_to'), sub: [it(T('lib.add_collection'), 'addcol')]}, {sep: 1},
        it(T('lib.refresh_info'), 'refresh'), it(T('lib.analyze'), 'analyze'), it(T('mn.match'), 'match'));
      if (!matched || matched.has(parseInt(ref, 10))) out.push(it(T('mn.unmatch'), 'unmatch'));  // 35.2: só com correspondência
      out.push(it(T('lib.grant_access'), 'access'), it(T('lib.delete'), 'delete'), it(T('mn.history'), 'history'));
      return out;
    }
    if (kind === 'video') {  // 34.6: sem Corrigir/Remover Correspondência nem Atualizar Informações
      out.push(it(T('lib.analyze'), 'analyze'), it(T('lib.grant_access'), 'access'), it(T('lib.delete'), 'delete'), it(T('mn.history'), 'history'));
      return out;
    }
    out.push(it(T('lib.analyze'), 'analyze'), it(T('mn.history'), 'history'), {sep: 1}, it(T('lib.delete'), 'delete'));
    return out;
  };

  // Organiza o menu de filme/série: itens do usuário, itens admin e "Copiar link" por último (25.3)
  function tidy(a) {
    var o = [];
    a.forEach(function (x) { if (x.sep && (!o.length || o[o.length - 1].sep)) return; o.push(x); });
    while (o.length && o[o.length - 1].sep) o.pop();
    return o;
  }
  function arrange(base, admin) {
    var copy = base.filter(function (x) { return x.copy !== undefined; });
    var rest = base.filter(function (x) { return x.copy === undefined; });
    var sv = rest.filter(function (x) { return x.l === T('det.save_file'); })[0], at = -1;  // admin: Salvar arquivo antes de Conceder Acesso (captura 52)
    admin.forEach(function (x, i) { if (x.act === 'access') at = i; });
    if (sv && at >= 0) { rest = rest.filter(function (x) { return x !== sv; }); admin = admin.slice(0, at).concat([sv], admin.slice(at)); }
    return tidy(rest.concat([{sep: 1}], admin, [{sep: 1}], copy));
  }

  document.addEventListener('click', function (e) {
    var more = e.target.closest('[data-more]'), dm = e.target.closest('[data-menu]');
    if ((menu && menu.contains(e.target)) || (subMenu && subMenu.contains(e.target))) return;
    if (more) {
      e.preventDefault(); e.stopPropagation();
      if (trigger === more) { close(); return; }
      var card = more.closest('.pcard'); if (card) open(more, cardItems(card));
      return;
    }
    if (dm && dm.dataset.menu && dm.dataset.menu.charAt(0) === '[') {
      e.preventDefault();
      if (trigger === dm) { close(); return; }
      var items = []; try { items = JSON.parse(dm.dataset.menu); } catch (err) {}
      if (window.sfAdmin && dm.dataset.adminItem) {
        var ai = dm.dataset.adminItem.split(':');
        if (ai[0] === 'movie' || ai[0] === 'show') items = arrange(items, window.sfAdminItems(ai[0], ai[1], dm.dataset.adminName));
        else items = items.concat([{sep: 1}], window.sfAdminItems(ai[0], ai[1], dm.dataset.adminName));
      }
      open(dm, items, e.detail === 0);
      return;
    }
    close();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { var t = trigger; close(); if (t && t.focus) t.focus(); return; }
    if (!menu || ['ArrowDown', 'ArrowUp', 'ArrowRight', 'ArrowLeft', 'Home', 'End'].indexOf(e.key) < 0) return;
    var act = document.activeElement, inSub = !!(subMenu && subMenu.contains(act)), cur = inSub ? subMenu : menu;
    var bs = [].slice.call(cur.querySelectorAll('button')), i = bs.indexOf(act);
    if (!bs.length) return;
    e.preventDefault();
    if (e.key === 'ArrowDown') bs[(i + 1) % bs.length].focus();
    else if (e.key === 'ArrowUp') bs[(i - 1 + bs.length) % bs.length].focus();
    else if (e.key === 'Home') bs[0].focus();
    else if (e.key === 'End') bs[bs.length - 1].focus();
    else if (e.key === 'ArrowRight' && !inSub && act && act.classList.contains('has-sub')) {
      if (subOwner !== act) act.click();
      var f = subMenu && subMenu.querySelector('button'); if (f) f.focus();
    } else if (e.key === 'ArrowLeft' && inSub) { var ow = subOwner; closeSub(); if (ow) ow.focus(); }
  });
  window.addEventListener('resize', close);
  window.addEventListener('scroll', close, true);
})();
