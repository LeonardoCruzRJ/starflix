// Abas Informações e Avançado (23.22).
(window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () {
  function fmtSize(b) { return SF_I18N.fmt.size(b, 2); }
  function fmtDur(s) { return SF_I18N.fmt.hm(s); }
  function box(f) {
    var i = f.info || {}, v = i.video || {}, a = (i.audio || [])[0] || {}, d = document.createElement('div');
    d.className = 'em-file';
    var p = document.createElement('div'); p.className = 'em-path'; p.textContent = f.path; d.appendChild(p);
    var bits = [];
    if (v.width) bits.push(v.width + '×' + v.height);
    if (v.codec) bits.push(T('ef.video', {codec: v.codec}));
    if (a.codec) bits.push(T('ef.audio', {codec: a.codec + (a.channels ? ' ' + a.channels + 'ch' : '')}));
    if (i.duration) bits.push(fmtDur(i.duration));
    bits.push(fmtSize(f.size));
    var m = document.createElement('div'); m.className = 'em-meta'; m.textContent = bits.join(' · '); d.appendChild(m);
    return d;
  }
  // Marcadores de abertura/créditos do episódio (48.3): grava na hora, sem passar pelo Salvar Alterações.
  function tm(s) { var m = Math.floor(s / 60), r = s - m * 60; return m + ':' + (r < 10 ? '0' : '') + r.toFixed(1).replace(/\.0$/, '').replace('.', SF_I18N.fmt.decsep()); }
  function parseTm(v) {
    v = String(v || '').trim().replace(',', '.'); if (!v) return NaN;
    var p = v.split(':'); if (p.length > 3) return NaN;
    return p.reduce(function (a, x) { return a * 60 + (x === '' ? NaN : Number(x)); }, 0);
  }
  function post(url, body) {
    return fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)}).then(function (r) {
      if (r.status === 401) { location.href = '/login'; throw new Error(T('common.session')); }
      return r.json().then(function (j) { if (!r.ok) throw new Error(SF_I18N.msg(j) || T('em.save_err')); return j; });
    });
  }
  function markers(pane, id) {
    var h = document.createElement('h3'); h.textContent = T('ef.markers'); h.className = 'em-h'; pane.appendChild(h);
    var box = document.createElement('div'); box.className = 'em-mk'; pane.appendChild(box);
    fetch('/markers/episode/' + id).then(function (r) { return r.json(); }).then(function (j) {
      var have = {}; ((j && j.markers) || []).forEach(function (m) { have[m.kind] = m; });
      [['intro', T('player.mark.intro')], ['credits', T('player.mark.credits')]].forEach(function (k) {
        var m = have[k[0]], row = document.createElement('div'); row.className = 'em-mk-row';
        row.innerHTML = '<span class="em-mk-lab"></span><input class="em-mk-s" placeholder="' + T('ef.start_ph') + '" aria-label="' + T('ef.start') + '"><input class="em-mk-e" placeholder="' + T('ef.end_ph') + '" aria-label="' + T('ef.end') + '">' +
          '<button type="button" class="em-mk-save">' + T('common.save') + '</button><button type="button" class="em-mk-del">' + T('common.remove') + '</button>' +
          '<span class="em-mk-apply"><input class="em-mk-shift" placeholder="' + T('ef.shift_ph') + '" aria-label="' + T('ef.shift_aria') + '"><button type="button" class="em-mk-season">' + T('ef.season') + '</button></span>' +
          '<span class="em-mk-msg"></span>';
        row.querySelector('.em-mk-lab').textContent = k[1];
        var s = row.querySelector('.em-mk-s'), e = row.querySelector('.em-mk-e'), msg = row.querySelector('.em-mk-msg'), del = row.querySelector('.em-mk-del'), ap = row.querySelector('.em-mk-apply');
        function paint() { del.hidden = ap.hidden = !m; if (m) { s.value = tm(m.start); e.value = tm(m.end); } }
        function say(t, bad) { msg.textContent = t; msg.classList.toggle('bad', !!bad); }
        row.querySelector('.em-mk-save').addEventListener('click', function () {
          var a = parseTm(s.value), b = parseTm(e.value);
          if (isNaN(a) || isNaN(b)) { say(T('ef.bad_tm'), 1); return; }
          post('/admin/markers/episode/' + id, {kind: k[0], start: a, end: b}).then(function (r) { m = r.marker; paint(); say(T('common.saved')); }).catch(function (x) { say(x.message, 1); });
        });
        del.addEventListener('click', function () {
          post('/admin/markers/episode/' + id, {kind: k[0], delete: true}).then(function () { m = null; s.value = e.value = ''; paint(); say(T('ef.removed')); }).catch(function (x) { say(x.message, 1); });
        });
        row.querySelector('.em-mk-season').addEventListener('click', function () {
          var sh = row.querySelector('.em-mk-shift').value.trim(), n = sh ? parseTm(sh.replace(/^[+-]/, '')) * (sh[0] === '-' ? -1 : 1) : 0;
          if (isNaN(n)) { say(T('ef.bad_shift'), 1); return; }
          sfConfirm(T('ef.season_q'), {title: T('ef.season'), ok: T('ef.apply')}).then(function (ok) {
            if (!ok) return;
            post('/admin/markers/episode/' + id + '/season', {kind: k[0], shift: n}).then(function (r) { say(Tn('ef.applied', r.count)); }).catch(function (x) { say(x.message, 1); });
          });
        });
        paint(); box.appendChild(row);
      });
    }).catch(function () { box.textContent = T('ef.mk_fail'); });
  }

  window.sfEditTabs.info = {render: function (pane, data) {
    if (data.kind === 'episode') markers(pane, data.ref);
    var h = document.createElement('h3'); h.textContent = T('ef.files'); h.className = 'em-h'; pane.appendChild(h);
    if (!data.files.length) { pane.insertAdjacentHTML('beforeend', '<p class="em-soon">' + T('ef.nofiles') + '</p>'); return; }
    data.files.forEach(function (f) { pane.appendChild(box(f)); });
    if (data.files.length > 1) {
      var sz = 0, du = 0; data.files.forEach(function (f) { sz += f.size || 0; du += (f.info && f.info.duration) || 0; });
      var t = document.createElement('div'); t.className = 'em-meta em-total';
      t.textContent = T('ef.total', {n: data.files.length, size: fmtSize(sz), dur: fmtDur(du)}); pane.appendChild(t);
    }
  }};

  var L = [['', T('det.default')], ['pt', T('lang.pt')], ['en', T('lang.en')], ['es', T('lang.es')], ['fr', T('lang.fr')], ['de', T('lang.de')], ['it', T('lang.it')], ['ja', T('lang.ja')], ['ko', T('lang.ko')], ['zh', T('lang.zh')], ['ru', T('lang.ru')]];
  var SHOW = [['audio_lang', T('ef.audio_lang'), L], ['sub_lang', T('ef.sub_lang'), L],
    ['sub_mode', T('ef.sub_mode'), [['', T('det.default')], ['off', T('ef.sub_off')], ['forced', T('ef.sub_forced')], ['foreign', T('ef.sub_foreign')]]]];
  var MOVIE = [['meta_lang', T('ef.meta_lang'), [['', T('ef.lib_default')], ['pt-BR', T('ef.pt_br')], ['en-US', T('lang.en')], ['es-ES', T('lang.es')], ['fr-FR', T('lang.fr')], ['de-DE', T('lang.de')], ['it-IT', T('lang.it')], ['ja-JP', T('lang.ja')]]],
    ['use_original', T('ef.use_original'), [['', T('ef.lib_default')], ['1', T('adv.yes')], ['0', T('adv.no')]]]];
  var COL = [['mode', T('ef.mode'), [['', T('ef.lib_default')], ['hide', T('lm.adv.coll.hide')], ['both', T('lm.adv.coll.both')]]]];
  window.sfEditTabs.advanced = {render: function (pane, data, api) {
    (data.kind === 'collection' ? COL : data.kind === 'movie' ? MOVIE : SHOW).forEach(function (s) {
      var lab = document.createElement('label'), sel = document.createElement('select'), cur = data.prefs[s[0]] || '';
      if (api.changes.prefs && s[0] in api.changes.prefs) cur = api.changes.prefs[s[0]];
      lab.className = 'em-sel'; lab.textContent = s[1];
      s[2].forEach(function (o) { var op = document.createElement('option'); op.value = o[0]; op.textContent = o[1]; sel.appendChild(op); });
      sel.value = cur;
      sel.addEventListener('change', function () { (api.changes.prefs = api.changes.prefs || {})[s[0]] = sel.value; api.markDirty(); });
      lab.appendChild(sel); pane.appendChild(lab);
    });
  }};
});
