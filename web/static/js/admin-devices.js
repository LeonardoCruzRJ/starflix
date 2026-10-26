// 52.6: cartão "Aparelhos" do Painel
(function () {
  var list = document.getElementById('dv-list');
  if (!list) return;
  function when(t) { return t ? SF_I18N.fmt.datetime(t) : '—'; }
  async function api(url, body) {
    var r = await fetch(url, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    if (r.status === 401) { location.href = '/login'; throw new Error('401'); }
    var j = {}; try { j = await r.json(); } catch (e) {}
    if (!r.ok) throw new Error(SF_I18N.msg(j) || T('common.action_failed'));
    return j;
  }
  function paint(d) {
    list.innerHTML = '';
    if (!d.devices.length) { list.innerHTML = ''; var e0 = document.createElement('p'); e0.className = 'la-empty'; e0.textContent = T('dvc.none'); list.appendChild(e0); return; }
    d.devices.forEach(function (x) {
      var row = document.createElement('div'); row.className = 'lm-row';
      row.innerHTML = '<div class="lm-name"></div><div class="lm-sub"></div><div class="lm-acts"><label class="hl-opt"><input type="checkbox"> <span></span></label><button type="button" class="la-btn"></button></div>';
      row.querySelector('label span').textContent = T('dvc.required'); row.querySelector('button').textContent = T('common.delete');
      row.children[0].textContent = x.label + ' · ' + x.user;
      row.children[1].textContent = x.summary + ' · ' + when(x.seen);
      var cb = row.querySelector('input'); cb.checked = x.required;
      cb.addEventListener('change', function () {
        api('/admin/devices/required', {key: x.key, required: cb.checked}).then(paint).catch(function (e) { cb.checked = !cb.checked; alert(e.message); });
      });
      row.querySelector('button').addEventListener('click', function () {
        sfConfirm(T('dvc.confirm', {name: x.label}), {title: T('dvc.delete_title'), ok: T('common.delete'), danger: true}).then(function (ok) {
          if (!ok) return;
          api('/admin/devices/delete', {key: x.key}).then(paint).catch(function (e) { alert(e.message); });
        });
      });
      list.appendChild(row);
    });
  }
  (window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () { return api('/admin/devices/data'); }).then(paint).catch(function (e) { list.innerHTML = ''; var p = document.createElement('p'); p.className = 'la-empty'; p.textContent = e.message; list.appendChild(p); });
})();
