// 59.5: cliente de i18n. T(chave, vars), Tn(chave, n), cache do catálogo, data-i18n*, evento sf:lang, Intl.
// Idioma ativo = <html lang>. Catálogo vem de /api/i18n/<idioma> (ETag) e fica em localStorage.
(function () {
  'use strict';
  var KEY = 'sf.i18n.', cat = {}, lang = norm(document.documentElement.lang) || 'pt-BR', ready;

  function norm(l) { return (l || '').replace('_', '-'); }
  function store(l, v) { try { if (v === undefined) return JSON.parse(localStorage.getItem(KEY + l) || 'null'); localStorage.setItem(KEY + l, JSON.stringify(v)); } catch (e) {} return null; }

  function fmt(s, vars) {
    return String(s).replace(/\{(\w+)\}/g, function (m, k) { return vars && vars[k] !== undefined ? vars[k] : m; });
  }
  function T(key, vars) {
    var s = cat[key];
    return s === undefined ? key : fmt(s, vars);
  }
  function Tn(key, n, vars) {
    var v = {n: n}, k; for (k in (vars || {})) v[k] = vars[k];
    var cat1;
    try { cat1 = new Intl.PluralRules(lang).select(n); } catch (e) { cat1 = n === 1 ? 'one' : 'other'; }
    var s = cat[key + '.' + cat1];
    if (s === undefined) s = cat[key + '.other'];
    return s === undefined ? key : fmt(s, v);
  }

  // 59.19: texto de um erro JSON do servidor ({code, vars, message, error}): T(code) quando a chave existe, senão o texto recebido.
  function msg(j) {
    if (!j) return '';
    if (j.code && (cat[j.code] !== undefined || cat[j.code + '.other'] !== undefined)) return j.vars && j.vars.n !== undefined ? Tn(j.code, j.vars.n, j.vars) : T(j.code, j.vars);
    return j.message || j.error || '';
  }

  function apply(root) {
    root = root || document;
    var map = [['data-i18n', null], ['data-i18n-title', 'title'], ['data-i18n-placeholder', 'placeholder'], ['data-i18n-aria', 'aria-label'], ['data-i18n-tip', 'data-tip']];
    map.forEach(function (m) {
      root.querySelectorAll('[' + m[0] + ']').forEach(function (el) {
        var k = el.getAttribute(m[0]); if (cat[k] === undefined && cat[k + '.other'] === undefined) return;
        var n = el.getAttribute('data-i18n-n'), txt = n !== null ? Tn(k, +n) : T(k);
        if (m[1]) el.setAttribute(m[1], txt); else el.textContent = txt;
      });
    });
  }

  function load(l) {
    l = norm(l) || lang;
    var c = store(l), h = {};
    if (c && c.etag) h['If-None-Match'] = c.etag;
    return fetch('/api/i18n/' + encodeURIComponent(l), {headers: h, credentials: 'same-origin'}).then(function (r) {
      if (r.status === 304 && c) return c.strings;
      if (!r.ok) throw 0;
      var etag = r.headers.get('ETag');
      return r.json().then(function (d) { store(l, {etag: etag, strings: d.strings}); return d.strings; });
    }).catch(function () { return c ? c.strings : {}; });
  }

  function use(l, strings) {
    lang = norm(l) || lang; cat = strings || {};
    document.documentElement.lang = lang;
    apply();
    document.dispatchEvent(new CustomEvent('sf:lang', {detail: {lang: lang}}));
  }

  // Aplica o cache na hora (sem piscar) e revalida em seguida.
  var cached = store(lang); if (cached && cached.strings) cat = cached.strings;
  ready = load(lang).then(function (s) { use(lang, s); return lang; });
  if (cached) apply(); else if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { apply(); });

  // 59.6: troca instantânea. Grava (perfil + cookie), aplica o catálogo no DOM, avisa os módulos (sf:lang) e busca de novo
  // os fragmentos montados no servidor ([data-sf-fragment="url"]). Tela sem window.SF_LIVE_LANG (ou <body data-live-lang>)
  // ainda tem texto fixo no servidor: recarrega sozinha.
  function refetch() {
    var els = document.querySelectorAll('[data-sf-fragment]');
    return Promise.all([].map.call(els, function (el) {
      return fetch(el.getAttribute('data-sf-fragment'), {credentials: 'same-origin'}).then(function (r) { return r.ok ? r.text() : null; })
        .then(function (h) { if (h !== null) { el.innerHTML = h; apply(el); } }).catch(function () {});
    }));
  }
  function set(l) {
    return fetch('/api/i18n/set', {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({lang: l})})
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return {ok: r.ok, status: r.status, error: msg(j)}; }); })
      .then(function (res) {
        if (!res.ok) return res;
        return load(l).then(function (s) {
          use(l, s);
          return refetch().then(function () {
            var live = window.SF_LIVE_LANG || (document.body && document.body.hasAttribute('data-live-lang'));
            if (!live) { res.reloaded = true; location.reload(); }
            return res;
          });
        });
      });
  }

  // Formatos pelo idioma ativo
  function safe(fn, fb) { try { return fn(); } catch (e) { return fb; } }
  var F = {
    number: function (n, o) { return safe(function () { return new Intl.NumberFormat(lang, o).format(n); }, String(n)); },
    date: function (d, o) { return safe(function () { return new Intl.DateTimeFormat(lang, o || {dateStyle: 'medium'}).format(new Date(d)); }, String(d)); },
    ago: function (d) {
      var s = (new Date(d).getTime() - Date.now()) / 1000, a = Math.abs(s);
      var u = a < 60 ? ['second', s] : a < 3600 ? ['minute', s / 60] : a < 86400 ? ['hour', s / 3600] : a < 2592000 ? ['day', s / 86400] : a < 31536000 ? ['month', s / 2592000] : ['year', s / 31536000];
      return safe(function () { return new Intl.RelativeTimeFormat(lang, {numeric: 'auto'}).format(Math.round(u[1]), u[0]); }, F.date(d));
    },
    duration: function (sec) {
      sec = Math.max(0, Math.round(sec)); var h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
      var p = function (x) { return (x < 10 ? '0' : '') + x; };
      return h ? h + ':' + p(m) + ':' + p(s) : m + ':' + p(s);
    },
    // d = casas decimais de MB para cima (B e KB sem decimais)
    size: function (b, d) {
      if (b == null) return '?';
      var u = ['B', 'KB', 'MB', 'GB', 'TB'], i = 0; while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
      return F.number(b, {minimumFractionDigits: 0, maximumFractionDigits: i > 1 ? (d === undefined ? 1 : d) : 0}) + ' ' + u[i];
    },
    // 59.20: casas decimais fixas, separador decimal, data e hora curtas, "há X" (epoch em segundos) e durações
    dec: function (n, d) { return F.number(n, {minimumFractionDigits: d, maximumFractionDigits: d}); },
    decsep: function () { return safe(function () { return new Intl.NumberFormat(lang).formatToParts(1.1).filter(function (p) { return p.type === 'decimal'; })[0].value; }, '.'); },
    datetime: function (sec) { return F.date(sec * 1000, {dateStyle: 'short', timeStyle: 'short'}); },
    agoTs: function (sec) { return F.ago(sec * 1000); },
    hm: function (s) { s = Math.round(s || 0); var h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60); return h ? T('fmt.dur.h_m', {h: h, m: m}) : T('fmt.dur.m', {m: m}); },
    hmShort: function (s) { s = Math.round(s || 0); if (!s) return ''; var h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60); return h ? T('fmt.dur.short_h_m', {h: h, m: ('0' + m).slice(-2)}) : T('fmt.dur.short_m', {m: m}); },
    minsec: function (s) { return s >= 60 ? T('fmt.dur.min_s', {m: Math.floor(s / 60), s: s % 60}) : T('fmt.dur.s', {s: s}); },
    clockH: function (s) { s = Math.round(s || 0); var h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60); return h ? T('fmt.dur.clock_h', {h: h, m: ('0' + m).slice(-2)}) : T('fmt.dur.m', {m: m}); },
    secs: function (v) { return T('fmt.sec', {n: (v > 0 ? '+' : v < 0 ? '\u2212' : '') + F.dec(Math.abs(v), 1)}); },
    compare: function (a, b) { return safe(function () { return new Intl.Collator(lang, {sensitivity: 'base', numeric: true}).compare(a, b); }, a < b ? -1 : a > b ? 1 : 0); }
  };

  window.SF_I18N = {T: T, Tn: Tn, msg: msg, apply: apply, load: load, use: use, set: set, ready: ready, fmt: F, get lang() { return lang; }};
  window.T = T; window.Tn = Tn;
})();
