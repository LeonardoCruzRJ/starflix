// Configurações de reprodução no celular (≤700px): lista + uma tela por item, trocadas por #hash (seta e voltar do aparelho funcionam).
// Salva com POST /account/settings (mesmas chaves do desktop) e atualiza o resumo da lista sem recarregar.
(window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () {  // 59.15: textos montados aqui precisam do catálogo
  'use strict';
  var root = document.getElementById('accm'); if (!root) return;
  var screens = {};
  root.querySelectorAll('.pem-s').forEach(function (s) { screens[s.dataset.s] = s; });
  function goBack() { if (history.length > 1 && location.hash) history.back(); else location.hash = ''; }

  function ctls(sec) { return sec.querySelectorAll('[data-key]'); }
  function read(sec) { var o = {}; ctls(sec).forEach(function (c) { o[c.dataset.key] = c.type === 'checkbox' ? c.checked : c.value; }); return o; }
  function txt(sec, key, v) {  // rótulo da opção (nos idiomas, "" = "Padrão")
    if (v === '' && (key === 'audio_lang' || key === 'sub_lang')) return T('set.default');
    var c = sec.querySelector('[data-key="' + key + '"]'), o = c && Array.prototype.filter.call(c.options, function (x) { return x.value === v; })[0];
    return o ? o.text : v;
  }
  var base = {};
  function summary(id) {
    var v = base[id], S = function (sid, k) { return txt(screens[sid], k, v[k]); };
    if (id === 'idioma') return S('idioma', 'lang');
    if (id === 'audio') return (v.auto ? T('acc.sum.track', {a: S('audio', 'audio_lang'), s: S('audio', 'sub_lang'), m: S('audio', 'sub_mode')}) : T('acc.sum.auto_off')) +
      '\n' + T('acc.sum.search', {a: S('audio', 'sdh'), b: S('audio', 'forced')});
    if (id === 'abertura') return T('acc.sum.skip', {a: S('abertura', 'skip_intro'), b: S('abertura', 'auto_next')});
    if (id === 'legenda') return T('acc.sum.sub', {a: S('legenda', 'sub_size'), b: S('legenda', 'sub_color'), c: S('legenda', 'sub_bg'), d: S('legenda', 'sub_pos')});
    if (id === 'assistidos') return S('assistidos', 'seen');
    return S('avaliacoes', 'reviews');
  }
  function paint(id) { root.querySelector('[data-sum="' + id + '"]').textContent = summary(id); }

  var prev = document.getElementById('m-sub-prev'), map = {sub_size: 'ssize', sub_color: 'scolor', sub_bg: 'sbg', sub_pos: 'spos'};
  function preview(sec) { if (prev && sec.dataset.s === 'legenda') ctls(sec).forEach(function (c) { prev.dataset[map[c.dataset.key]] = c.value; }); }

  Object.keys(screens).forEach(function (id) {
    if (!id) return;
    var sec = screens[id], save = sec.querySelector('.pem-save'), err = sec.querySelector('.pem-err');
    base[id] = read(sec); paint(id);
    function check() { preview(sec); save.disabled = JSON.stringify(read(sec)) === JSON.stringify(base[id]); }
    sec._reset = function () {
      ctls(sec).forEach(function (c) { var k = c.dataset.key; if (c.type === 'checkbox') c.checked = !!base[id][k]; else c.value = base[id][k]; });
      err.textContent = ''; check();
    };
    ctls(sec).forEach(function (c) { c.addEventListener('change', check); });
    save.addEventListener('click', function () {
      save.disabled = true; err.textContent = '';
      var vals = read(sec);
      (id === 'idioma' ? window.SF_I18N.set(vals.lang).then(function (a) { return [a, a]; }) : fetch('/account/settings', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({values: vals})})
        .then(function (r) { return r.json().then(function (j) { return [r, j]; }); }))
        .then(function (a) { if (a[0].status === 401) { location.href = '/login'; throw 0; } return a; })
        .then(function (a) {
          if (!a[0].ok) { err.textContent = SF_I18N.msg(a[1]) || T('common.save_failed'); check(); return; }
          base[id] = vals; paint(id);
          if (id === 'idioma') { goBack(); return; }  // 59.6: SF_I18N.set já aplicou o idioma (ou recarregou)
          if (id === 'assistidos') document.documentElement.dataset.seen = vals.seen;  // o selo ✓ dos cards muda na hora
          goBack();
        }).catch(function (e) { if (e !== 0) { err.textContent = T('common.conn_failed'); check(); } });
    });
  });

  function route() {
    var h = location.hash.slice(1), name = screens[h] ? h : '';
    Object.keys(screens).forEach(function (k) { screens[k].hidden = k !== name; });
    if (screens[name]._reset) screens[name]._reset();
    window.scrollTo(0, 0);
  }
  window.addEventListener('hashchange', route);
  root.addEventListener('click', function (e) {
    var b = e.target.closest('.pem-back'); if (!b) return;
    e.preventDefault();
    if (b.dataset.back === 'main') { if (history.length > 1 && document.referrer) history.back(); else location.href = '/profile/edit'; }
    else goBack();
  });
  route();
});
