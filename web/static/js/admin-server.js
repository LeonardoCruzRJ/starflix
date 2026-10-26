// 58.1: Configurações → Servidor (nome, endereço externo, mDNS)
(function () {
  var $ = function (i) { return document.getElementById(i); }, name = $('sv-name'), url = $('sv-url'), mdns = $('sv-mdns'), port = $('sv-port'), save = $('sv-save'), test = $('sv-test'),
    msg = $('sv-msg'), warn = $('sv-warn'), local = $('sv-local'), sid = $('sv-id');
  function say(t, bad) { msg.textContent = t || ''; msg.className = 'hl-msg' + (bad ? ' bad' : ''); }
  function fill(d) {
    name.value = d.name; url.value = d.url; mdns.checked = d.mdns; port.value = d.port; sid.textContent = d.id;
    name.disabled = url.disabled = mdns.disabled = port.disabled = test.disabled = false; save.disabled = true;
    warn.hidden = !d.warning; warn.textContent = d.warning || '';
    local.innerHTML = '';
    if (!d.local.length) { var e = document.createElement('li'); e.textContent = T('sv.no_local'); local.appendChild(e); }
    d.local.forEach(function (u) { var li = document.createElement('li'), c = document.createElement('code'); c.textContent = u; li.appendChild(c); local.appendChild(li); });
  }
  function json(r) { return r.json().then(function (j) { if (!r.ok) throw new Error(SF_I18N.msg(j) || T('common.error')); return j; }); }
  (window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () { return fetch('/admin/server/data'); }).then(json).then(fill).catch(function (e) { say(e.message, true); });
  [name, url, mdns, port].forEach(function (e) { e.addEventListener('input', function () { save.disabled = false; say(''); }); e.addEventListener('change', function () { save.disabled = false; say(''); }); });
  // 60.1: porta nova = o servidor reinicia; a página espera ele voltar na porta nova e segue para lá (só se foi aberta direto pela porta antiga)
  function moved(j) {
    say(T('sv.restarting', {port: j.new_port})); port.value = j.new_port;
    var direct = location.port === String(j.port), target = location.protocol + '//' + location.hostname + ':' + j.new_port, tries = 0;
    (function wait() {
      setTimeout(function () {
        var probe = direct ? fetch(target + '/health', {cache: 'no-store', mode: 'no-cors'})
          : fetch('/admin/server/data', {cache: 'no-store'}).then(function (r) { if (!r.ok) throw new Error('down'); return r; });
        probe.then(function () {
          if (direct) location.href = target + location.pathname;
          else fetch('/admin/server/data').then(json).then(fill).then(function () { say(T('common.saved')); }).catch(function () { });
        }, function () { if (++tries < 40) wait(); else say(T('sv.unreachable'), true); });
      }, 3000);
    })();
  }
  save.addEventListener('click', function () {
    save.disabled = true;
    fetch('/admin/server/save', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name.value, url: url.value, mdns: mdns.checked, port: parseInt(port.value, 10)})})
      .then(json).then(function (j) { fill(j); if (j.restart) moved(j); else say(T('common.saved')); })
      .catch(function (e) { save.disabled = false; say(e.message, true); });
  });
  // Testar: o navegador consulta o /api/server-info do endereço (58.2, CORS aberto) e compara o identificador
  test.addEventListener('click', function () {
    if (!url.value.trim()) { say(T('sv.need_url'), true); return; }
    test.disabled = true; say(T('common.testing'));
    fetch('/admin/server/normalize', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({url: url.value})}).then(json).then(function (j) {
      url.value = j.url;
      if (location.protocol === 'https:' && j.url.indexOf('http:') === 0) throw new Error(T('sv.https_block'));
      var ac = new AbortController(), t = setTimeout(function () { ac.abort(); }, 6000);
      return fetch(j.url + '/api/server-info', {cache: 'no-store', signal: ac.signal}).then(function (r) { clearTimeout(t); return r.json(); }).then(function (h) {
        if (!h || h.app !== 'starflix') throw new Error(T('sv.not_starflix'));
        if (h.id !== sid.textContent) throw new Error(T('sv.other_server', {name: h.name || '?'}));
        say(T('sv.reached'));
      }, function () { clearTimeout(t); throw new Error(T('sv.unreachable')); });
    }).catch(function (e) { say(e.message, true); }).then(function () { test.disabled = false; });
  });
})();

// 60.6: "?" ao lado do mDNS: explicação ao passar o mouse (ou foco/toque)
(function () {
  var q = document.getElementById('sv-q'), t = document.getElementById('sv-tip');
  if (!q || !t) return;
  var box = q.parentNode;
  function set(o) { t.hidden = !o; q.setAttribute('aria-expanded', o ? 'true' : 'false'); }
  box.addEventListener('mouseenter', function () { set(true); });
  box.addEventListener('mouseleave', function () { set(false); });
  q.addEventListener('focus', function () { set(true); });
  q.addEventListener('blur', function () { set(false); });
  q.addEventListener('click', function (e) { e.stopPropagation(); set(t.hidden); });
  document.addEventListener('click', function (e) { if (!box.contains(e.target)) set(false); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') set(false); });
})();
