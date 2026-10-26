// Opções do Avançado (28.12, capturas 86 a 90), reutilizável no Editar (28.13). window.sfLibAdv.render(pane, prefs, data, onChange(key)).
(window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () {
  'use strict';
  function el(t, c, x) { var e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; }
  var VIS = { all: T('lm.adv.vis.all'), hide_home: T('lm.adv.vis.hide_home'), hide_all: T('lm.adv.vis.hide_all') };
  var AGENT = { tmdb: 'TMDB / TVDB', none: T('lm.adv.agent.none') };
  var COLL = { 'default': T('lm.adv.coll.default'), hide: T('lm.adv.coll.hide'), both: T('lm.adv.coll.both') };

  function render(pane, prefs, data, onChange, type) {
    function row(label, help) { var r = el('div', 'la-opt'); var l = el('label', 'la-line'); if (label) l.appendChild(el('span', '', label)); r.appendChild(l); if (help) r.appendChild(el('p', 'lw-hint la-help', help)); pane.appendChild(r); return l; }
    function sel(key, label, map, help) {
      var l = row(label, help), s = el('select');
      Object.keys(map).forEach(function (k) { var o = el('option', '', map[k]); o.value = k; if (prefs[key] === k) o.selected = true; s.appendChild(o); });
      s.addEventListener('change', function () { prefs[key] = s.value; onChange(key); }); l.appendChild(s);
    }
    function chk(key, label, help) {
      var l = row('', help), c = el('input'); c.type = 'checkbox'; c.checked = !!prefs[key];
      c.addEventListener('change', function () { prefs[key] = c.checked; onChange(key); });
      l.appendChild(c); l.appendChild(el('span', '', label));
    }
    if (type === 'video') {  // 34.4: sem TMDB/TVDB — só Visibilidade, recursos locais e miniaturas
      sel('visibility', T('lm.adv.visibility'), VIS, T('lm.adv.vis_help'));
      chk('local_art', T('lm.adv.local_art'), T('lm.adv.local_art_help_v'));
      chk('thumbs', T('lm.adv.thumbs'), T('lm.adv.thumbs_help'));
      chk('trickplay', T('lm.adv.trickplay'), T('lm.adv.trickplay_help'));
      return;
    }
    sel('agent', T('lm.adv.agent'), AGENT, T('lm.adv.agent_help'));
    sel('visibility', T('lm.adv.visibility'), VIS, T('lm.adv.vis_help'));
    sel('cert_country', T('lm.adv.cert'), data.cert_countries, T('lm.adv.cert_help'));
    chk('original_titles', T('lm.adv.orig'), T('lm.adv.orig_help'));
    chk('lang_art', T('lm.adv.lang_art'), T('lm.adv.lang_art_help'));
    chk('local_art', T('lm.adv.local_art'), T('lm.adv.local_art_help'));
    if (type === 'show') chk('detect_markers', T('lm.adv.markers'), T('lm.adv.markers_help'));
    chk('trickplay', T('lm.adv.trickplay'), T('lm.adv.trickplay_help'));
    chk('adult', T('lm.adv.adult'), T('lm.adv.adult_help'));
    var rs = { tmdb: 'TMDB' }; if (data.omdb) { rs.imdb = 'IMDb'; rs.rt = 'Rotten Tomatoes'; }
    sel('rating_source', T('lm.adv.rating'), rs, T('lm.adv.rating_help'));
    sel('collection_mode', T('lm.adv.coll'), COLL, T('lm.adv.coll_help'));
  }
  window.sfLibAdv = { render: render };
});
