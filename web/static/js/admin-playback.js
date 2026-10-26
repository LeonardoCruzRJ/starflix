// 50.3: Configurações → Reprodução (HDR e Direct play)
(function () {
  var $ = function (i) { return document.getElementById(i); }, hdr = $('pb-hdr'), h = $('pb-h'), dp = $('pb-dp'), ws = $('pb-ws'), we = $('pb-we'), gb = $('pb-gb'), save = $('pb-save'), msg = $('pb-msg');
  function fill(d) {
    h.innerHTML = '';
    d.heights.forEach(function (n) { var o = document.createElement('option'); o.value = n; o.textContent = n + 'p'; h.appendChild(o); });
    hdr.value = d.hdr_mode; h.value = d.hdr_max_height; dp.value = d.direct_policy; var w = d.optimize_window.split('-'); ws.value = w[0]; we.value = w[1]; gb.value = d.optimize_max_gb;
    hdr.disabled = h.disabled = dp.disabled = ws.disabled = we.disabled = gb.disabled = false; save.disabled = true;
  }
  (window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () { return fetch('/admin/playback/data'); }).then(function (r) { return r.json(); }).then(fill);
  [hdr, h, dp, ws, we, gb].forEach(function (e) { e.addEventListener('change', function () { save.disabled = false; msg.textContent = ''; }); });
  save.addEventListener('click', function () {
    save.disabled = true;
    fetch('/admin/playback/save', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({hdr_mode: hdr.value, hdr_max_height: parseInt(h.value, 10), direct_policy: dp.value,
        optimize_window: (ws.value || '02:00') + '-' + (we.value || '07:00'), optimize_max_gb: parseInt(gb.value || '0', 10)})})
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(SF_I18N.msg(j) || T('common.error')); return j; }); })
      .then(function (j) { fill(j); msg.textContent = T('common.saved'); })
      .catch(function (e) { save.disabled = false; msg.textContent = e.message; });
  });
})();

// 53.2: "?" ao lado do título abre/fecha a explicação
(function () {
  var q = document.getElementById('pb-q'), t = document.getElementById('pb-tip');
  if (!q || !t) return;
  function set(o) { t.hidden = !o; q.setAttribute('aria-expanded', o ? 'true' : 'false'); }
  q.addEventListener('click', function (e) { e.stopPropagation(); set(t.hidden); });
  document.addEventListener('click', function (e) { if (!t.contains(e.target)) set(false); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') set(false); });
})();
