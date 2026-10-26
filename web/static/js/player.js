(function () {
  var root = document.getElementById('player');
  var kind = root.dataset.kind, id = root.dataset.id;
  var base = '/stream/' + kind + '/' + id;
  var video = document.getElementById('video');
  var ui = document.getElementById('ui');
  var seek = document.getElementById('seek');
  var $ = function (s) { return document.getElementById(s); };
  var selAudio = $('audio'), selSubs = $('subs'), selQuality = $('quality');

  var duration = 0;      // duração total do arquivo (s)
  var probed = false;    // true quando a duração veio do ffprobe
  var offset = 0;        // posição absoluta onde a sessão atual começa (transcode com ?start=)
  var mode = 'direct';
  var sid = null;        // sessão de transcode ativa
  var hls = null;
  var cues = [];
  var subOffset = 0;     // 47.1: atraso da legenda (s); positivo = a legenda aparece mais tarde
  var subKey = '';       // chave da legenda ativa (ext:<arquivo> | emb:<índice>); vazio = nenhuma
  var subUrl = '';
  var subTracks = {};    // url -> {key, offset} (vem de /subs)
  var offTimer = null, offPending = null, osdTimer = null;
  var seeking = false;
  var loadToken = 0;
  var lastSave = 0;
  var retried = false;
  var safe = false;      // 52.3: direct/remux por `caps` falhou: repete uma vez com transcode completo (mode=safe)
  var capsUsed = false;
  var forceHls = false;  // direct play falhou: usa HLS daqui em diante
  var loaded = false;    // true depois que a mídia carregou e foi posicionada; antes disso não há posição a salvar

  // sessão expirada (401 JSON): avisa e volta para o login
  var _fetch = window.fetch;
  window.fetch = function () {
    return _fetch.apply(this, arguments).then(function (r) {
      if (r.status === 401) {
        showError(T('player.session_expired'));
        setTimeout(function () { location.href = '/login'; }, 1500);
      }
      return r;
    });
  };

  function abs() { return offset + (video.currentTime || 0); }
  function fmt(t) {
    t = Math.max(0, Math.floor(t));
    var h = Math.floor(t / 3600), m = Math.floor(t / 60) % 60, s = t % 60;
    return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(s).padStart(2, '0');
  }
  function post(url, body) {
    return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  }
  function showError(msg) { var e = $('error'); e.textContent = msg; e.hidden = !msg; }
  function busy(on) { $('spinner').hidden = !on; }

  // ---------- carregar mídia ----------
  function stopSession() {
    if (hls) { hls.destroy(); hls = null; }
    if (sid) { navigator.sendBeacon('/stream/session/' + sid + '/stop'); sid = null; }
  }

  var loading = false;   // true enquanto a carga mais recente espera a resposta do servidor
  var stale = [];        // sessões de cargas antigas a encerrar (evita ffmpeg órfão até o TTL)
  function flushStale() {
    stale.forEach(function (s) { if (s !== sid) navigator.sendBeacon('/stream/session/' + s + '/stop'); });
    stale = [];
  }
  function load(start, autoplay) {
    var token = ++loadToken;
    loading = true;
    loaded = false;
    if (autoplay !== 'retry') retried = false;
    showError(''); busy(true);
    stopSession();
    video.pause();
    var q = new URLSearchParams();
    if (selAudio.value) q.set('audio', selAudio.value);
    if (selQuality.value && selQuality.value !== 'original') q.set('quality', selQuality.value);
    if (start > 0) q.set('start', Math.floor(start));
    if (safe) q.set('mode', 'safe'); else if (forceHls) q.set('mode', 'hls');
    try { if (window.matchMedia && matchMedia('(dynamic-range: high)').matches) q.set('hdr', '1'); } catch (e) {}  // 50.3: tela HDR toca HDR sem converter
    return (window.SFCaps ? SFCaps.ready : Promise.resolve()).then(function () {
      var cp = !safe && window.SFCaps ? SFCaps.get() : '';
      capsUsed = !!cp;
      if (cp) q.set('caps', cp);
      return fetch(base + '/play?' + q.toString(), { method: 'POST' });
    })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(SF_I18N.msg(j) || T('player.start_failed')); return j; }); })
      .then(function (j) {
        if (token !== loadToken) {  // carga antiga: encerra a sessão dela (menos se for a mesma da carga atual)
          if (j.sid) { stale.push(j.sid); if (!loading) flushStale(); }
          return;
        }
        loading = false;
        mode = j.mode; sid = j.sid || null;
        var hn = $('hdr-note');  // 50.4: aviso da conversão HDR → SDR nos Ajustes
        if (hn) { hn.hidden = !j.hdr_sdr; hn.textContent = j.hdr_sdr ? 'HDR → SDR' + (j.dv5 ? ' (' + T('player.dv5') + ')' : '') : ''; }
        flushStale();
        offset = j.mode === 'direct' ? 0 : (j.offset || 0);
        var local = j.mode === 'direct' ? start : 0;
        function ready() {
          if (token !== loadToken) return;
          if (local > 0) video.currentTime = local;
          loaded = true;
          busy(false);
          if (autoplay !== false) video.play().catch(function () {});
        }
        if (j.mode === 'direct') {
          video.src = j.url;
          video.addEventListener('loadedmetadata', ready, { once: true });
        } else if (window.Hls && Hls.isSupported()) {
          hls = new Hls({ maxBufferLength: 30 });
          hls.loadSource(j.url);
          hls.attachMedia(video);
          hls.on(Hls.Events.MANIFEST_PARSED, ready);
          hls.on(Hls.Events.ERROR, function (_, d) {
            if (!d.fatal) return;
            if (!retried && token === loadToken) { retried = true; load(abs(), 'retry'); return; }
            if (capsUsed && !safe && token === loadToken) { safe = true; load(abs(), 'retry'); return; }
            showError(T('player.stream_error', {code: d.details})); busy(false);
          });
        } else {
          video.src = j.url;  // Safari: HLS nativo
          video.addEventListener('loadedmetadata', ready, { once: true });
        }
      })
      .catch(function (e) {
        if (token !== loadToken) return;  // erro de carga antiga não mexe na carga nova
        loading = false; flushStale();
        busy(false); showError(e.message);
      });
  }

  // ---------- legendas (renderizadas à mão para respeitar o offset) ----------
  function tsec(s) {
    var p = s.replace(',', '.').split(':').map(parseFloat);
    return p.length === 3 ? p[0] * 3600 + p[1] * 60 + p[2] : p[0] * 60 + p[1];
  }
  function parseVTT(text) {
    var out = [];
    text.replace(/\r/g, '').split(/\n\n+/).forEach(function (block) {
      var lines = block.split('\n');
      var i = lines.findIndex(function (l) { return l.indexOf('-->') > -1; });
      if (i < 0) return;
      var m = lines[i].match(/([\d:.,]+)\s*-->\s*([\d:.,]+)/);
      if (!m) return;
      out.push({ s: tsec(m[1]), e: tsec(m[2]), t: lines.slice(i + 1).join('\n').replace(/<[^>]+>/g, '') });
    });
    return out;
  }
  var subToken = 0;
  function setSubs(url) {
    var token = ++subToken;  // ignora respostas de uma legenda anterior
    flushOffset();
    cues = []; $('subtitle').textContent = '';
    var tr = url ? subTracks[url] : null;
    subUrl = url || ''; subKey = tr ? tr.key : ''; subOffset = tr ? tr.offset : 0;
    paintOffset();
    if (!url) return;
    fetch(url).then(function (r) { return r.text(); })
      .then(function (t) { if (token === subToken) cues = parseVTT(t); })
      .catch(function () {});
  }
  function renderSub() {
    var t = abs() - subOffset, txt = '';
    for (var i = 0; i < cues.length; i++) { if (t >= cues[i].s && t <= cues[i].e) { txt = cues[i].t; break; } }
    var el = $('subtitle');
    if (el.textContent !== txt) el.textContent = txt;
  }

  // ---------- atraso da legenda (47.1) ----------
  function fmtOff(v) { return SF_I18N.fmt.secs(v); }
  function paintOffset() {
    $('delay-val').textContent = fmtOff(subOffset);
    var off = !subKey;
    $('delay-row').classList.toggle('off', off);
    ['delay-minus', 'delay-plus'].forEach(function (i) { $(i).disabled = off; });
    $('delay-reset').disabled = off || subOffset === 0;
  }
  function osd(msg) {
    var el = $('osd'); el.textContent = msg; el.classList.add('show');
    clearTimeout(osdTimer); osdTimer = setTimeout(function () { el.classList.remove('show'); }, 1500);
  }
  function flushOffset() {  // grava o último atraso pendente (troca de legenda, saída da página)
    clearTimeout(offTimer); offTimer = null;
    if (!offPending) return;
    var p = offPending; offPending = null;
    fetch(base + '/subs/offset', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(p), keepalive: true }).catch(function () {});
  }
  function changeOffset(delta) {
    if (!subKey) { osd(T('player.delay_need_sub')); return; }
    var v = Math.round((subOffset + delta) * 10) / 10;
    v = Math.max(-300, Math.min(300, v));
    if (v === subOffset) return;
    subOffset = v;
    if (subTracks[subUrl]) subTracks[subUrl].offset = v;
    offPending = { key: subKey, offset: v };
    clearTimeout(offTimer); offTimer = setTimeout(flushOffset, 600);
    paintOffset(); renderSub();
    osd(T('player.sub_osd', {v: fmtOff(v)}));
  }
  function holdButton(btn, dir) {  // clique = 0,1 s; segurar = 0,5 s por vez
    var t1 = null, t2 = null;
    function stop() { clearTimeout(t1); clearInterval(t2); t1 = t2 = null; }
    btn.addEventListener('pointerdown', function (e) {
      if (e.button) return;
      e.preventDefault();
      changeOffset(dir * 0.1);
      t1 = setTimeout(function () { t2 = setInterval(function () { changeOffset(dir * 0.5); }, 250); }, 500);
    });
    ['pointerup', 'pointerleave', 'pointercancel', 'blur'].forEach(function (ev) { btn.addEventListener(ev, stop); });
    btn.addEventListener('click', function (e) { if (e.detail === 0) changeOffset(dir * 0.1); });  // teclado (Enter/Espaço no botão)
  }
  holdButton($('delay-minus'), -1);
  holdButton($('delay-plus'), 1);
  $('delay-reset').addEventListener('click', function () { changeOffset(-subOffset); this.blur(); });
  paintOffset();

  // ---------- estilo da legenda (47.2) ----------
  (function () {
    var btn = $('sty-btn'), panel = $('sty-panel'), el = $('subtitle');
    btn.addEventListener('click', function () { panel.hidden = !panel.hidden; btn.setAttribute('aria-expanded', panel.hidden ? 'false' : 'true'); this.blur(); });
    panel.querySelectorAll('select').forEach(function (sel) {
      sel.addEventListener('change', function () {
        el.dataset[sel.dataset.attr] = sel.value;
        var v = {}; v[sel.dataset.sty] = sel.value;
        post('/account/settings', { values: v }).catch(function () {});
      });
    });
  })();

  function fillSubs(subs) {
    selSubs.innerHTML = ''; subTracks = {};
    (subs.external || []).concat(subs.embedded || []).forEach(function (s) { if (s.key) subTracks[s.url] = { key: s.key, offset: s.offset || 0 }; });
    opt(selSubs, '', T('player.sub_off'));
    (subs.external || []).forEach(function (s) { opt(selSubs, s.url, T('player.sub_ext', {name: s.lang || s.title})); });
    (subs.embedded || []).forEach(function (s) { opt(selSubs, s.url, (s.title || (s.lang || T('player.track', {n: s.index}))).toUpperCase()); });
  }

  // ---------- buscar legenda no SubDL (47.3, só admin) ----------
  (function () {
    var open = $('ss-open'); if (!open) return;
    var box = $('ss'), sel = $('ss-lang'), list = $('ss-list'), msg = $('ss-msg'), have = $('ss-have'), lang = '', busyPick = false;
    function say(t, err) { msg.textContent = t || ''; msg.classList.toggle('err', !!err); }
    function close() { box.hidden = true; }
    function api(path, body) {
      return fetch(base + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })
        .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(SF_I18N.msg(j) || T('player.ss.failed')); return j; }); });
    }
    function paintHave(files) {
      have.hidden = !files.length; have.innerHTML = '';
      files.forEach(function (f) {
        var b = document.createElement('button'); b.type = 'button'; b.className = 'p-dreset'; b.textContent = T('player.ss.remove', {file: f});
        b.addEventListener('click', function () {
          sfConfirm(T('player.ss.delete_q', {file: f}), {title: T('player.ss.delete_title'), ok: T('common.delete'), danger: true}).then(function (ok) {
            if (!ok) return;
            api('/subs/remove', { file: f }).then(function () { return reloadSubs(null); }).then(function () { search(false); }).catch(function (e) { say(e.message, true); });
          });
        });
        have.appendChild(b);
      });
    }
    function reloadSubs(activateKey) {  // recarrega a lista e ativa a legenda nova
      var cur = selSubs.value;
      return fetch(base + '/subs').then(function (r) { return r.json(); }).then(function (subs) {
        fillSubs(subs);
        var all = (subs.external || []).concat(subs.embedded || []), want = null;
        if (activateKey) want = all.filter(function (x) { return x.key === activateKey; })[0];
        else want = all.filter(function (x) { return x.url === cur; })[0];
        selSubs.value = want ? want.url : '';
        setSubs(selSubs.value);
      });
    }
    function paint(j) {
      lang = j.lang;
      if (!sel.options.length) j.langs.forEach(function (l) { opt(sel, l.code, l.label); });
      sel.value = lang;
      $('ss-budget').textContent = T('player.ss.budget', {used: j.budget.used, max: j.budget.max}) + (j.cached ? ' · ' + T('player.ss.cached') : '');
      list.innerHTML = '';
      say(j.candidates.length ? '' : T('player.ss.none'));
      j.candidates.forEach(function (c) {
        var li = document.createElement('li'); li.tabIndex = 0;
        var d = document.createElement('div'); d.className = 'ss-rel';
        d.textContent = c.release || T('player.ss.no_name');
        var m = document.createElement('span'); m.className = 'ss-meta';
        m.textContent = [c.author && T('player.ss.by', {author: c.author}), c.downloads && Tn('player.ss.downloads', c.downloads), c.pack && T('player.ss.pack')].filter(Boolean).join(' · ');
        d.appendChild(m); li.appendChild(d);
        [c.hi && 'SDH', c.forced && T('player.ss.forced')].filter(Boolean).forEach(function (t) { var g = document.createElement('span'); g.className = 'ss-tag'; g.textContent = t; li.appendChild(g); });
        function choose() {
          if (busyPick) return; busyPick = true; li.classList.add('busy'); say(T('player.ss.downloading'));
          api('/subs/pick', { lang: lang, id: c.id }).then(function (r) { return reloadSubs(r.key); })
            .then(function () { busyPick = false; close(); osd(T('player.ss.activated')); })
            .catch(function (e) { busyPick = false; li.classList.remove('busy'); say(e.message, true); });
        }
        li.addEventListener('click', choose);
        li.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); choose(); } });
        list.appendChild(li);
      });
      paintHave(j.downloaded || []);
    }
    function search(refresh) {
      say(T('player.ss.searching')); list.innerHTML = '';
      api('/subs/search', { lang: sel.value || undefined, refresh: !!refresh }).then(paint).catch(function (e) { say(e.message, true); });
    }
    open.addEventListener('click', function () { settings(false); box.hidden = false; search(false); this.blur(); });
    $('ss-x').addEventListener('click', close);
    box.addEventListener('click', function (e) { if (e.target === box) close(); });
    sel.addEventListener('change', function () { search(false); });
    $('ss-refresh').addEventListener('click', function () { search(true); });
    document.addEventListener('keydown', function (e) { if (!box.hidden) { e.stopPropagation(); if (e.key === 'Escape') close(); } }, true);
  })();

  // ---------- UI ----------
  function opt(sel, value, label) { var o = document.createElement('option'); o.value = value; o.textContent = label; sel.appendChild(o); }

  // ---------- pular abertura (48.2) ----------
  var introMark = null, skipPref = root.dataset.skipintro || 'ask', introDone = false, introHide = null;
  function inIntro(t) { return introMark && t >= introMark.start - 0.3 && t < introMark.end - 1; }
  function hideSkip() { $('skip').hidden = true; clearTimeout(introHide); introHide = null; }
  function doSkip() { if (!introMark) return; introDone = true; hideSkip(); seekTo(introMark.end); osd(T('player.skipped')); }
  function checkIntro(t) {
    if (!introMark || !loaded || skipPref === 'never') return;
    if (!inIntro(t)) { if (!$('skip').hidden) hideSkip(); if (skipPref === 'ask' && (t < introMark.start - 1 || t >= introMark.end)) introDone = false; return; }
    if (introDone) return;
    if (skipPref === 'always') { doSkip(); return; }
    if ($('skip').hidden && !introHide) {
      $('skip').hidden = false;
      introHide = setTimeout(function () { introDone = true; hideSkip(); }, 8000);  // some sozinho; volta só ao reentrar na janela
    }
  }
  $('skip').addEventListener('click', function () { doSkip(); this.blur(); });
  if (kind === 'episode') {
    fetch('/markers/episode/' + id).then(function (r) { return r.json(); }).then(function (j) {
      var ms = (j && j.markers) || [];
      if (skipPref !== 'never') introMark = ms.filter(function (m) { return m.kind === 'intro'; })[0] || null;
      creditsMark = ms.filter(function (m) { return m.kind === 'credits'; })[0] || (j && j.credits_fallback ? {kind: 'credits', start: j.credits_fallback, end: 0} : null);  // 57.22: sem marcador, os últimos 45 s
    }).catch(function () {});
  }

  // ---------- créditos e próximo episódio (48.4) ----------
  // Só com marcador de créditos; sem marcador segue como antes (passa ao terminar).
  var creditsMark = null, autoNext = root.dataset.autonext !== 'off', ncDismissed = false, ncTimer = null, ncLeft = 0, nextUrl = null;
  function ncHide() { $('nextcard').hidden = true; clearInterval(ncTimer); ncTimer = null; }
  function goNext() {
    ncHide(); ncDismissed = true;
    save(true).then(function (r) { location.href = nextUrl || (r && r.next ? carried('/watch/episode/' + r.next.id) : root.dataset.back); })
      .catch(function () { location.href = root.dataset.back; });
  }
  function ncPaint() { $('nc-sub').textContent = autoNext ? T('player.nc.in', {n: ncLeft}) : T('player.nc.started'); }
  function checkCredits(t) {
    if (!creditsMark || !nextUrl || !loaded || (window.sfQueue && sfQueue.size())) return;
    var inside = t >= creditsMark.start - 0.3;
    if (!inside) { if (!$('nextcard').hidden) ncHide(); if (t < creditsMark.start - 1) ncDismissed = false; return; }
    if (ncDismissed || !$('nextcard').hidden) return;
    $('nextcard').hidden = false; ncLeft = 10; ncPaint();
    if (autoNext) ncTimer = setInterval(function () {
      if (video.paused) return;  // pausado: a contagem espera
      ncLeft--; ncPaint(); if (ncLeft <= 0) goNext();
    }, 1000);
  }
  $('nc-go').addEventListener('click', function () { goNext(); });
  $('nc-cancel').addEventListener('click', function () { ncHide(); ncDismissed = true; this.blur(); });

  // ---------- marcação manual (48.3, só admin) ----------
  if (kind === 'episode' && $('mark-row')) (function () {
    var marks = {}, draft = {intro: {}, credits: {}}, selK = $('mark-kind');
    function paint() {
      var m = marks[selK.value], d = draft[selK.value];
      $('mark-val').textContent = m ? fmt(m.start) + ' – ' + fmt(m.end) : (d.start != null || d.end != null ? (d.start != null ? fmt(d.start) : '?') + ' – ' + (d.end != null ? fmt(d.end) : '?') : '—');
      $('mark-clear').disabled = !m;
    }
    function post(body) {
      return fetch('/admin/markers/episode/' + id, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)})
        .then(function (r) {
          if (r.status === 401) { location.href = '/login'; throw new Error(T('player.mark.session')); }
          return r.json().then(function (j) { if (!r.ok) throw new Error(SF_I18N.msg(j) || T('player.mark.save_err')); return j; });
        });
    }
    function done(k, m) {
      marks[k] = m; if (!m) draft[k] = {};
      if (k === 'intro' && skipPref !== 'never') { introMark = m; introDone = false; }
      if (k === 'credits') { creditsMark = m; ncDismissed = false; }
      paint();
    }
    function mark(part) {
      var k = selK.value, d = draft[k]; d[part] = Math.round(abs() * 10) / 10;
      if (d.start == null || d.end == null) { paint(); osd(T(part === 'start' ? 'player.mark.start_set' : 'player.mark.end_set', {t: fmt(d[part])})); return; }
      if (d.end <= d.start) { osd(T('player.mark.end_after')); paint(); return; }
      post({kind: k, start: d.start, end: d.end}).then(function (j) { done(k, j.marker); osd(T('player.mark.saved.' + k)); })
        .catch(function (e) { osd(e.message); });
    }
    $('mark-start').addEventListener('click', function () { mark('start'); this.blur(); });
    $('mark-end').addEventListener('click', function () { mark('end'); this.blur(); });
    $('mark-clear').addEventListener('click', function () {
      var k = selK.value; this.blur();
      post({kind: k, delete: true}).then(function () { done(k, null); osd(T('player.mark.cleared')); }).catch(function (e) { osd(e.message); });
    });
    selK.addEventListener('change', paint);
    fetch('/markers/episode/' + id).then(function (r) { return r.json(); }).then(function (j) {
      ((j && j.markers) || []).forEach(function (m) { marks[m.kind] = m; }); paint();
    }).catch(function () {});
    paint();
  })();

  function update() {
    var t = abs();
    checkIntro(t); checkCredits(t);
    if (!seeking && duration) seek.value = Math.min(1000, t / duration * 1000);
    $('time').textContent = fmt(t) + ' / ' + fmt(duration);
    $('play').querySelector('use').setAttribute('href', video.paused ? '#i-play' : '#i-pause');
    seek.style.setProperty('--p', (duration ? Math.min(100, t / duration * 100) : 0) + '%');
    renderSub();
  }

  function seekTo(t) {
    t = Math.max(0, Math.min(duration || t, t));
    if (mode === 'direct') { video.currentTime = t; return; }
    var local = t - offset, b = video.buffered;
    var end = b.length ? b.end(b.length - 1) : 0;
    if (local >= 0 && local < end - 1) video.currentTime = local;  // já gerado
    else load(t);                                                  // reinicia a sessão a partir de t
  }

  function save(final) {
    // antes de carregar/posicionar a posição seria 0 e apagaria a de retomada (voltar durante a espera do HLS)
    if (!final && (!loaded || abs() < 1)) return;
    var b = { position: final ? duration : abs() };
    // sem ffprobe, em HLS o <video> só conhece o trecho gerado: a duração só é confiável no fim ou quando veio do servidor
    if (final || probed || mode === 'direct') b.duration = duration;
    var body = JSON.stringify(b);
    if (final) return fetch('/progress/' + kind + '/' + id, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body }).then(function (r) { return r.json(); });
    navigator.sendBeacon('/progress/' + kind + '/' + id, new Blob([body], { type: 'text/plain' }));
  }

  var hideTimer;
  function wake() {
    ui.classList.remove('hidden'); root.classList.remove('idle');
    clearTimeout(hideTimer);
    hideTimer = setTimeout(function () { if (!video.paused && $('settings').hidden) { ui.classList.add('hidden'); root.classList.add('idle'); } }, 3000);
  }

  function toggle() { video.paused ? video.play() : video.pause(); }
  function fullscreen() {
    if (document.fullscreenElement) document.exitFullscreen();
    else root.requestFullscreen && root.requestFullscreen();
  }

  // ---------- eventos ----------
  video.addEventListener('timeupdate', function () {
    update();
    var now = Date.now();
    if (!video.paused && now - lastSave >= 10000) { lastSave = now; save(false); }
  });
  video.addEventListener('durationchange', function () {  // ffprobe falhou: usa a duração do próprio vídeo
    if (!probed && isFinite(video.duration) && video.duration > 0) { duration = offset + video.duration; update(); }
  });
  video.addEventListener('play', update);
  video.addEventListener('pause', function () { update(); save(false); wake(); });
  video.addEventListener('error', function () {
    if (mode !== 'direct' || !video.error) return;
    if (capsUsed && !safe) { safe = true; load(abs(), true); return; }
    if (forceHls) { showError(T('player.cant_play')); busy(false); return; }
    forceHls = true;
    load(abs(), true);
  });
  video.addEventListener('waiting', function () { busy(true); });
  video.addEventListener('playing', function () { busy(false); retried = false; });  // nova expiração de sessão também se recupera
  video.addEventListener('click', toggle);
  video.addEventListener('dblclick', fullscreen);
  video.addEventListener('ended', function () {
    save(true).then(function (r) {
      var q = window.sfQueue && sfQueue.shift();  // 31.5: a fila tem prioridade sobre o próximo episódio
      if (q) location.href = sfQueue.url(q);
      else if (r && r.next && !(creditsMark && !autoNext)) location.href = carried('/watch/episode/' + r.next.id);
      else location.href = root.dataset.back;
    }).catch(function () { location.href = root.dataset.back; });  // sessão expirada/servidor fora: não fica parado no fim
  });
  // controles estilo Plex (23.11)
  function relSeek(d) { seekTo(abs() + d); }
  $('back10').addEventListener('click', function () { relSeek(-10); this.blur(); });
  $('fwd30').addEventListener('click', function () { relSeek(30); this.blur(); });
  $('stop').addEventListener('click', function () { location.href = root.dataset.back; });
  if (kind === 'episode') {
    fetch('/next/episode/' + id).then(function (r) { return r.json(); }).then(function (j) {
      if (j && j.next) { nextUrl = carried('/watch/episode/' + j.next.id); $('next').hidden = false; }
    }).catch(function () {});
  }
  if (window.sfQueue) {
    var qh = sfQueue.get()[0];  // item que já está tocando sai da fila
    if (qh && qh.k === kind && String(qh.id) === String(id)) sfQueue.shift();
    if (sfQueue.size()) { $('next').hidden = false; $('next').dataset.tip = T('player.next_queue'); $('next').setAttribute('aria-label', T('player.next_queue')); }
  }
  $('next').addEventListener('click', function () {
    var q = window.sfQueue && sfQueue.shift();
    if (q) location.href = sfQueue.url(q);
    else if (nextUrl) location.href = nextUrl;
  });
  var sbtn = $('settings-btn'), spop = $('settings');
  function settings(open) { spop.hidden = !open; sbtn.setAttribute('aria-expanded', open ? 'true' : 'false'); wake(); }
  sbtn.addEventListener('click', function (e) { e.stopPropagation(); settings(spop.hidden); this.blur(); });
  document.addEventListener('click', function (e) { if (!spop.hidden && !spop.contains(e.target)) settings(false); });
  var vol = $('vol'), mute = $('mute');
  function paintVol() {
    var off = video.muted || video.volume === 0;
    mute.querySelector('use').setAttribute('href', off ? '#i-volume-off' : '#i-volume');
    vol.value = off ? 0 : Math.round(video.volume * 100);
  }
  try { var sv = parseFloat(localStorage.getItem('sf.vol')); if (sv >= 0 && sv <= 1) video.volume = sv; } catch (e) {}
  vol.addEventListener('input', function () {
    video.muted = false; video.volume = vol.value / 100;
    try { localStorage.setItem('sf.vol', String(video.volume)); } catch (e) {}
  });
  mute.addEventListener('click', function () { video.muted = !video.muted; this.blur(); });
  video.addEventListener('volumechange', paintVol);
  paintVol();
  // blur: botão focado + Espaço alternaria duas vezes (keydown do atalho + clique no keyup)
  $('play').addEventListener('click', function () { toggle(); this.blur(); });
  $('fs').addEventListener('click', function () { fullscreen(); this.blur(); });
  seek.addEventListener('input', function () { seeking = true; seek.style.setProperty('--p', seek.value / 10 + '%'); $('time').textContent = fmt(seek.value / 1000 * duration) + ' / ' + fmt(duration); });
  seek.addEventListener('change', function () { seeking = false; seekTo(seek.value / 1000 * duration); });
  // 49.3: miniaturas na barra (sprites do servidor, 49.1); sem miniaturas mostra só o tempo
  (function () {
    var tip = $('seek-tip'), img = $('seek-img'), tm = $('seek-time'), man = null, drag = false;
    fetch('/trickplay/' + kind + '/' + id + '/manifest.json').then(function (r) { return r.ok ? r.json() : null; })
      .then(function (m) { if (m && m.width && m.cols) { man = m; img.style.width = m.width + 'px'; img.style.height = m.height + 'px'; } }).catch(function () {});
    function show(e) {
      if (!duration) return;
      var r = seek.getBoundingClientRect(), f = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)), t = f * duration;
      tm.textContent = fmt(t);
      var half = (man ? man.width + 4 : 60) / 2, x = Math.max(half, Math.min(r.width - half, f * r.width));
      tip.style.left = (x + (r.left - seek.parentNode.getBoundingClientRect().left)) + 'px';
      if (man) {
        var i = Math.max(0, Math.min(man.count - 1, Math.floor(t / man.interval))), per = man.cols * man.rows, n = Math.floor(i / per), l = i % per;
        img.hidden = false;
        img.style.backgroundImage = 'url(/trickplay/' + kind + '/' + id + '/' + (n + 1) + '.jpg)';
        img.style.backgroundSize = man.cols * man.width + 'px ' + man.rows * man.height + 'px';
        img.style.backgroundPosition = -(l % man.cols) * man.width + 'px ' + -Math.floor(l / man.cols) * man.height + 'px';
      } else img.hidden = true;
      tip.hidden = false;
    }
    function hide() { if (!drag) tip.hidden = true; }
    seek.addEventListener('pointermove', show);
    seek.addEventListener('pointerdown', function (e) { drag = true; show(e); });
    window.addEventListener('pointerup', function () { drag = false; tip.hidden = true; });
    window.addEventListener('pointercancel', function () { drag = false; tip.hidden = true; });
    seek.addEventListener('pointerleave', hide);
  })();
  selAudio.addEventListener('change', function () { load(abs()); });
  selQuality.addEventListener('change', function () { load(abs()); });
  selSubs.addEventListener('change', function () { setSubs(selSubs.value); });
  ['mousemove', 'touchstart', 'keydown'].forEach(function (ev) { document.addEventListener(ev, wake); });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !$('settings').hidden) { $('settings').hidden = true; return; }
    if (e.target.tagName === 'SELECT' || e.target.id === 'vol') return;
    if (e.key === ' ') { e.preventDefault(); toggle(); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); seekTo(abs() + 10); }  // preventDefault: o slider focado não move junto
    else if (e.key === 'ArrowLeft') { e.preventDefault(); seekTo(abs() - 10); }
    else if (e.key === 'f' || e.key === 'F') fullscreen();
    else if ((e.key === 's' || e.key === 'S') && !e.ctrlKey && !e.metaKey && !e.altKey && inIntro(abs())) doSkip();
    else if ((e.key === 'g' || e.key === 'G' || e.key === 'h' || e.key === 'H') && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();  // G adianta, H atrasa (0,1 s; segurando, 0,5 s a cada 250 ms)
      var now = Date.now();
      if (e.repeat && now - holdKeyAt < 250) return;
      if (e.repeat) holdKeyAt = now;
      changeOffset((e.key === 'g' || e.key === 'G' ? -1 : 1) * (e.repeat ? 0.5 : 0.1));
    }
  });
  var holdKeyAt = 0;
  window.addEventListener('pagehide', function () { flushOffset(); if (duration) save(false); stopSession(); });

  // ---------- preferências de áudio/legenda (23.27) ----------
  var L2 = {por: 'pt', pt: 'pt', pob: 'pt', portuguese: 'pt', eng: 'en', en: 'en', english: 'en', spa: 'es', es: 'es', spanish: 'es',
    fra: 'fr', fre: 'fr', fr: 'fr', french: 'fr', deu: 'de', ger: 'de', de: 'de', german: 'de', ita: 'it', it: 'it', italian: 'it',
    jpn: 'ja', ja: 'ja', japanese: 'ja', kor: 'ko', ko: 'ko', korean: 'ko', zho: 'zh', chi: 'zh', zh: 'zh', chinese: 'zh', rus: 'ru', ru: 'ru', russian: 'ru'};
  function lang2(v) { v = String(v || '').toLowerCase().split(/[-_.\s]/)[0]; return L2[v] || ''; }
  var prefAudio = root.dataset.audio || '', prefSub = root.dataset.sub || '', prefMode = root.dataset.submode || '', prefSdh = root.dataset.sdh === 'sdh', prefForced = root.dataset.forced === 'forced';
  var qs = new URLSearchParams(location.search), carry = new URLSearchParams();
  if (qs.get('audio')) carry.set('audio', qs.get('audio'));
  if (qs.get('sub')) carry.set('sub', qs.get('sub'));
  function carried(u) { var c = carry.toString(); return c ? u + '?' + c : u; }
  function applyPrefs(info, subs) {
    var audio = (info.info && info.info.audio) || [], aLang = '';
    if (prefAudio) {
      var hit = audio.filter(function (a) { return lang2(a.lang) === prefAudio; })[0];
      if (hit) { selAudio.value = hit.index; }
    }
    var cur = audio.filter(function (a) { return String(a.index) === selAudio.value; })[0] || audio[0];
    aLang = cur ? lang2(cur.lang) : '';
    if (prefSub === 'off' || prefMode === 'off') return;
    var want = prefSub !== 'off' ? prefSub : '';
    var list = (subs.external || []).map(function (s) { return {url: s.url, lang: lang2(s.lang), text: (s.lang || '') + ' ' + (s.title || '')}; })
      .concat((subs.embedded || []).map(function (s) { return {url: s.url, lang: lang2(s.lang), text: (s.lang || '') + ' ' + (s.title || '')}; }));
    function isForced(x) { return /forced|forçad/i.test(x.text); }  // i18n-ok: reconhece o nome da faixa, não é texto da interface
    function isSdh(x) { return /sdh|\bhi\b|deficien|hearing/i.test(x.text); }
    function best(arr) { var b = null, bs = -1; arr.forEach(function (x) { var sc = (isForced(x) === prefForced ? 2 : 0) + (isSdh(x) === prefSdh ? 1 : 0); if (sc > bs) { b = x; bs = sc; } }); return b; }
    var pick = null;
    if (prefMode === 'forced') pick = list.filter(function (x) { return isForced(x) && (!want || x.lang === want); })[0] || list.filter(isForced)[0];
    else if (prefMode === 'foreign') {
      if (aLang && aLang !== (want || 'pt')) pick = list.filter(function (x) { return x.lang === (want || 'pt') && !isForced(x); })[0];
    } else if (want) pick = best(list.filter(function (x) { return x.lang === want; }));
    if (pick) { selSubs.value = pick.url; setSubs(pick.url); }
  }

  // ---------- início ----------
  var wanted = new URLSearchParams(location.search).get('start');
  Promise.all([
    window.SF_I18N ? SF_I18N.ready : Promise.resolve(),
    fetch(base + '/info').then(function (r) { return r.json(); }),
    fetch(base + '/subs').then(function (r) { return r.json(); }).catch(function () { return {}; }),
    fetch('/progress/' + kind + '/' + id).then(function (r) { return r.json(); }).catch(function () { return {}; })
  ]).then(function (res) {
    var info = res[1], subs = res[2], prog = res[3];
    duration = (info.info && info.info.duration) || 0;
    probed = duration > 0;

    ((info.info && info.info.audio) || []).forEach(function (a, i) {
      opt(selAudio, a.index, [a.title || (a.lang || T('player.track', {n: i + 1})).toUpperCase(), (a.codec || '').toUpperCase(), a.channels ? a.channels + 'ch' : ''].filter(Boolean).join(' · '));
    });
    if (!selAudio.options.length) { opt(selAudio, '', T('player.default')); }
    (info.qualities || ['original']).forEach(function (q) { opt(selQuality, q, q === 'original' ? T('player.original') : q); });
    fillSubs(subs);

    applyPrefs(info, subs);
    var start = wanted !== null ? parseFloat(wanted) || 0 : (!prog.watched && prog.position > 5 ? prog.position : 0);
    return load(start, true);
  }).catch(function () { showError(T('player.load_failed')); });
  wake();
})();
