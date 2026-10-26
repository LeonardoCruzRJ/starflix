// 51.3: cartão "Backup" do Painel
(function () {
  var $ = function (i) { return document.getElementById(i); };
  if (!$('bk')) return;
  var info = $('bk-info'), list = $('bk-list'), run = $('bk-run'), days = $('bk-days'), keep = $('bk-keep'), save = $('bk-save'), msg = $('bk-msg'), timer = null;
  function when(t) { return t ? SF_I18N.fmt.datetime(t) : '—'; }
  function size(n) { return SF_I18N.fmt.size(n); }
  async function api(url, body) {
    var r = await fetch(url, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    if (r.status === 401) { location.href = '/login'; throw new Error('401'); }
    var j = {}; try { j = await r.json(); } catch (e) {}
    if (!r.ok) throw new Error(SF_I18N.msg(j) || T('common.action_failed'));
    return j;
  }
  function paint(d) {
    var b = d.backups[0];
    info.textContent = d.running ? T('bk.running') : T('bk.info', {last: b ? when(d.last || b.mtime) + ' (' + size(b.size) + ')' : T('bk.none_yet'),
      next: d.days ? (!d.last ? T('bk.next_soon') : when(d.next)) : T('bk.off')});
    run.disabled = d.running; run.textContent = d.running ? T('bk.doing') : T('bk.run');
    if (document.activeElement !== days) days.value = d.days;
    if (document.activeElement !== keep) keep.value = d.keep;
    days.disabled = keep.disabled = save.disabled = false;
    list.innerHTML = '';
    d.backups.forEach(function (x) {
      var row = document.createElement('div'); row.className = 'lm-row bk-row';
      row.innerHTML = '<div class="lm-name"></div><div class="lm-sub"></div><div class="bk-acts"><button type="button" class="la-btn bk-restore"></button><a class="la-btn" download></a><button type="button" class="la-btn bk-del"></button></div>';
      var dl = row.querySelector('a'), del = row.querySelector('.bk-del'), rest = row.querySelector('.bk-restore');
      dl.textContent = T('bk.download'); del.textContent = T('common.delete'); rest.textContent = T('bk.restore');
      row.children[0].textContent = x.name; row.children[0].title = x.name; row.children[1].textContent = when(x.mtime) + ' · ' + size(x.size);
      dl.href = '/admin/backup/' + encodeURIComponent(x.name);
      rest.disabled = d.running;
      rest.addEventListener('click', function () { restore(x); });
      del.addEventListener('click', async function () {
        if (!await sfConfirm(T('bk.confirm', {name: x.name}), {title: T('bk.delete_title'), ok: T('common.delete'), danger: true})) return;
        try { paint(await api('/admin/backup/' + encodeURIComponent(x.name) + '/delete', {})); } catch (e) { msg.textContent = e.message; }
      });
      list.appendChild(row);
    });
    if (!d.backups.length) { var e0 = document.createElement('p'); e0.className = 'la-empty'; e0.textContent = T('bk.empty'); list.appendChild(e0); }
    clearTimeout(timer); if (d.running) timer = setTimeout(load, 1500);
  }
  // 60.10: Restaurar: o servidor para, restaura e sobe sozinho; a tela de abertura segura o usuário e, quando ele volta, a página recarrega
  var wait = $('bk-wait'), waitMsg = $('bk-wait-msg'), waitReload = $('bk-wait-reload');
  function boot() { return fetch('/health', {cache: 'no-store'}).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) { return j && j.boot || null; }).catch(function () { return null; }); }
  function showWait() {
    wait.hidden = false; document.documentElement.style.overflow = 'hidden';
    var logo = $('restore-logo');  // o logo anima ~3,5 s: recomeça em laço enquanto espera
    if (logo && logo.setCurrentTime) { var again = function () { try { logo.setCurrentTime(0); } catch (e) { } }; again(); setInterval(again, 5500); }
  }
  function hideWait() { wait.hidden = true; document.documentElement.style.overflow = ''; }
  async function restore(x) {
    if (!await sfConfirm(T('bk.restore_confirm', {name: x.name}), {title: T('bk.restore_title'), ok: T('bk.restore'), danger: true})) return;
    msg.textContent = '';
    var boot0 = await boot();
    try { await api('/admin/backup/' + encodeURIComponent(x.name) + '/restore', {}); } catch (e) { msg.textContent = e.message; return; }
    showWait();
    var started = Date.now(), down = false;
    (function poll() {
      setTimeout(async function () {
        var b = await boot();
        if (b === null) down = true;
        if (b !== null && (b !== boot0 || (boot0 === null && down))) {  // processo novo (ou voltou depois de cair): terminou
          var res = null;
          try { res = await api('/admin/backup/restore-result'); } catch (e) { }
          if (res && res.ok === false) {
            hideWait();
            msg.textContent = res.key && window.T ? T(res.key, res.vars || {}) : (res.msg || T('common.action_failed'));
            load();
          } else location.reload();
          return;
        }
        if (Date.now() - started > 180000) { waitMsg.textContent = T('bk.restore_timeout'); waitReload.hidden = false; return; }
        poll();
      }, 1500);
    })();
  }
  waitReload.addEventListener('click', function () { location.reload(); });
  async function load() { try { paint(await api('/admin/backup/list')); } catch (e) { info.textContent = T('bk.read_fail'); } }
  run.addEventListener('click', async function () {
    run.disabled = true; msg.textContent = '';
    try { await api('/admin/backup/run', {}); } catch (e) { msg.textContent = e.message; }
    load();
  });
  save.addEventListener('click', async function () {
    msg.textContent = '';
    try { paint(await api('/admin/backup/settings', {days: days.value, keep: keep.value})); msg.textContent = T('common.saved'); } catch (e) { msg.textContent = e.message; }
  });
  (window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(load);
})();
