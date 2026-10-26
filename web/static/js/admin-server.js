// 58.1: Configurações → Servidor (nome, endereço externo, mDNS)
(function () {
  var $ = function (i) { return document.getElementById(i); }, name = $('sv-name'), url = $('sv-url'), mdns = $('sv-mdns'), lang = $('sv-lang'), save = $('sv-save'), test = $('sv-test'),
    msg = $('sv-msg'), warn = $('sv-warn'), local = $('sv-local'), sid = $('sv-id');
  function say(t, bad) { msg.textContent = t || ''; msg.className = 'hl-msg' + (bad ? ' bad' : ''); }
  function fill(d) {
    name.value = d.name; url.value = d.url; mdns.checked = d.mdns; lang.value = d.lang; sid.textContent = d.id;
    name.disabled = url.disabled = mdns.disabled = lang.disabled = test.disabled = false; save.disabled = true;
    warn.hidden = !d.warning; warn.textContent = d.warning || '';
    local.innerHTML = '';
    if (!d.local.length) { var e = document.createElement('li'); e.textContent = T('sv.no_local'); local.appendChild(e); }
    d.local.forEach(function (u) { var li = document.createElement('li'), c = document.createElement('code'); c.textContent = u; li.appendChild(c); local.appendChild(li); });
  }
  function json(r) { return r.json().then(function (j) { if (!r.ok) throw new Error(SF_I18N.msg(j) || T('common.error')); return j; }); }
  (window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () { return fetch('/admin/server/data'); }).then(json).then(fill).catch(function (e) { say(e.message, true); });
  [name, url, mdns, lang].forEach(function (e) { e.addEventListener('input', function () { save.disabled = false; say(''); }); e.addEventListener('change', function () { save.disabled = false; say(''); }); });
  save.addEventListener('click', function () {
    save.disabled = true;
    fetch('/admin/server/save', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name.value, url: url.value, mdns: mdns.checked, lang: lang.value})})
      .then(json).then(function (j) { fill(j); say(T('common.saved')); })
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
