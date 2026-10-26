/* Confirmação no estilo do site (substitui window.confirm): sfConfirm(mensagem, {title, ok, cancel, danger}) -> Promise<boolean>.
   Formulários com data-confirm="mensagem" (e opcionalmente data-ok, data-title, data-danger) também passam por ele. */
(function () {
  'use strict';
  if (window.sfConfirm) return;
  var current = false;

  function el(t, c, x) { var e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; }

  window.sfConfirm = function (message, opts) {
    opts = opts || {};
    if (current) return Promise.resolve(false);
    current = true;
    var rdy = window.SF_I18N ? window.SF_I18N.ready : Promise.resolve();  // 59.8: textos padrão vêm do catálogo
    return rdy.then(function () { return new Promise(function (resolve) {
      var prev = document.activeElement;
      var htmlHad = document.documentElement.classList.contains('em-open');
      var ov = el('div', 'em-overlay sfc-overlay');
      var win = el('div', 'em-win sfc-win');
      win.setAttribute('role', 'alertdialog'); win.setAttribute('aria-modal', 'true');
      var head = el('div', 'em-head'), title = el('span', '', opts.title || T('common.confirm'));
      var x = el('button', 'em-x', '✕'); x.type = 'button'; x.setAttribute('aria-label', T('common.close'));
      head.appendChild(title); head.appendChild(x);
      var body = el('div', 'sfc-msg', message);
      var foot = el('div', 'em-foot');
      var no = el('button', 'em-btn em-cancel', opts.cancel || T('common.cancel')); no.type = 'button';
      var yes = el('button', 'em-btn ' + (opts.danger ? 'em-danger' : 'em-save'), opts.ok || T('common.ok')); yes.type = 'button';
      foot.appendChild(no); foot.appendChild(yes);
      win.appendChild(head); win.appendChild(body); win.appendChild(foot);
      ov.appendChild(win);
      document.body.appendChild(ov);
      document.documentElement.classList.add('em-open');

      function done(v) {
        window.removeEventListener('keydown', onKey, true);
        ov.remove();
        if (!htmlHad) document.documentElement.classList.remove('em-open');
        current = false;
        if (prev && prev.focus) { try { prev.focus(); } catch (e) { /* elemento removido */ } }
        resolve(v);
      }
      function onKey(e) {
        e.stopImmediatePropagation();  // nada por baixo (modais, player) reage enquanto a confirmação está aberta
        if (e.key === 'Escape') { e.preventDefault(); done(false); }
        else if (e.key === 'Tab') {
          e.preventDefault();
          var order = [x, no, yes], i = order.indexOf(document.activeElement);
          order[(i + (e.shiftKey ? -1 : 1) + order.length) % order.length].focus();
        }
      }
      window.addEventListener('keydown', onKey, true);
      ov.addEventListener('mousedown', function (e) { if (e.target === ov) done(false); });
      x.addEventListener('click', function () { done(false); });
      no.addEventListener('click', function () { done(false); });
      yes.addEventListener('click', function () { done(true); });
      (opts.danger ? no : yes).focus();
    }); });
  };

  document.addEventListener('submit', function (e) {
    var f = e.target, m = f && f.getAttribute && f.getAttribute('data-confirm');
    if (!m || f.__sfOk) return;
    e.preventDefault();
    window.sfConfirm(m, { title: f.getAttribute('data-title') || undefined, ok: f.getAttribute('data-ok') || undefined, danger: f.hasAttribute('data-danger') })
      .then(function (ok) { if (ok) { f.__sfOk = true; f.submit(); } });
  }, true);
})();
