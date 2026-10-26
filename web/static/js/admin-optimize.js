// 52.10: cartão "Versões otimizadas" do Painel
(window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () {
  var list = document.getElementById('op-list');
  if (!list) return;
  var info = document.getElementById('op-info'), bp = document.getElementById('op-pause'), bc = document.getElementById('op-clear'), timer = null;
  async function api(url, body) {
    var r = await fetch(url, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    if (r.status === 401) { location.href = '/login'; throw new Error('401'); }
    var j = {}; try { j = await r.json(); } catch (e) {}
    if (!r.ok) throw new Error(SF_I18N.msg(j) || T('common.action_failed'));
    return j;
  }
  function size(b) { return SF_I18N.fmt.size(b); }
  function dur(s) { return SF_I18N.fmt.hm(Math.max(Math.round(s), 60)); }
  function row(name, sub) {
    var d = document.createElement('div'); d.className = 'lm-row';
    d.innerHTML = '<div class="lm-name"></div><div class="lm-sub"></div>';
    d.children[0].textContent = name; d.children[1].textContent = sub || '';
    list.appendChild(d);
  }
  function paint(d) {
    var wp = d.window.split('-');
    info.textContent = T('op.info', {ready: Tn('op.ready', d.ok), used: size(d.used), max: d.max_gb ? T('op.max', {n: d.max_gb}) : '',
      window: T('op.window', {a: wp[0], b: wp[1]}), state: d.in_window ? T('op.in') : T('op.out'), paused: d.paused ? T('op.paused') : ''});
    bp.textContent = d.paused ? T('op.resume') : T('pn.opt.pause');
    bp.onclick = function () { api('/admin/optimize/pause', {paused: !d.paused}).then(paint).catch(function (e) { alert(e.message); }); };
    bc.onclick = function () {
      sfConfirm(T('op.confirm'), {title: T('op.confirm_title'), ok: T('common.delete'), danger: true}).then(function (ok) {
        if (!ok) return;
        api('/admin/optimize/clear', {}).then(paint).catch(function (e) { alert(e.message); });
      });
    };
    list.innerHTML = '';
    if (d.running) {
      var r = d.running;
      row(T('op.running', {title: r.title}), Math.round(r.progress * 100) + '%' + (r.eta ? T('op.eta', {t: dur(r.eta)}) : '') + (r.manual ? T('op.manual') : ''));
    }
    if (d.queue.total) {
      row(Tn('op.queue', d.queue.total), d.queue.items.map(function (x) { return x.title; }).join(', ') + (d.queue.total > d.queue.items.length ? '…' : ''));
    }
    d.skips.forEach(function (x) { row(T(x.status === 'skip' ? 'op.skip' : 'op.fail', {title: x.title}), x.reason); });
    if (!list.children.length) { var e0 = document.createElement('p'); e0.className = 'la-empty'; e0.textContent = T('op.empty'); list.appendChild(e0); }
  }
  function load() { api('/admin/optimize/data').then(paint).catch(function (e) { info.textContent = e.message; }); }
  load();
  timer = setInterval(function () { if (!document.hidden) load(); }, 5000);
});
