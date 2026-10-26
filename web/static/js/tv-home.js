/* 56.4: abas Explorar (uma fileira por biblioteca, até 40 itens, visão salva do perfil) e Coleções (coleções de cada biblioteca) — aba sem dado não aparece.
   56.3: Início no visual da TV (computador, >700 px) — o item em foco (mouse ou teclado, 350 ms parado) troca o fundo (sfHeroBg), o logo,
   o subtítulo, a linha de metadados, o selo de classificação e a sinopse; relógio no alto. Dados de /api/tv/movie|show|episode|collection. */
(function () {
  var box = document.getElementById("tvh");
  if (!box || !window.matchMedia("(min-width: 701px)").matches || !window.sfHeroBg) return;
  var $ = function (id) { return document.getElementById(id); };
  var logo = $("tvh-logo"), title = $("tvh-title"), sub = $("tvh-sub"), meta = $("tvh-meta"), rate = $("tvh-rate"), ov = $("tvh-ov");
  var cache = {}, timer = null, current = "";

  function minutes(sec) {
    var m = Math.round((sec || 0) / 60);
    return m <= 0 ? "" : (m >= 60 ? Math.floor(m / 60) + "h " + (m % 60) + " min" : m + " min");
  }
  function dateBr(s) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || ""); return m ? m[3] + "/" + m[2] + "/" + m[1] : ""; }
  function get(path) {
    return fetch(path, { credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (r) { if (!r.ok) throw r.status; return r.json(); });
  }

  /* qual item o cartão representa: {key, kind, id, ep} */
  function target(card) {
    var a = card.querySelector(".pcard-link"), pl = card.querySelector(".pcard-play");
    var href = a ? a.getAttribute("href") : "", play = pl ? pl.getAttribute("href") : "", m;
    if (card.dataset.collection) return { key: "c" + card.dataset.collection, kind: "collection", id: card.dataset.collection };
    if ((m = /^\/movie\/(\d+)/.exec(href))) return { key: "m" + m[1], kind: "movie", id: m[1] };
    if ((m = /^\/show\/(\d+)/.exec(href))) {
      var e = /^\/watch\/episode\/(\d+)/.exec(play || "");
      return { key: "s" + m[1] + (e ? "e" + e[1] : ""), kind: "show", id: m[1], ep: e ? e[1] : null };
    }
    if ((m = /^\/watch\/episode\/(\d+)/.exec(href))) return { key: "e" + m[1], kind: "episode", id: m[1] };
    if ((m = /^\/watch\/movie\/(\d+)/.exec(href))) return { key: "m" + m[1], kind: "movie", id: m[1] };
    return null;
  }

  function fromMedia(j, h) {
    var im = j.images || {};
    h.bd = im.backdrop || im.poster || "";
    h.logo = im.logo || "";
    h.rating = j.content_rating || "";
    h.overview = j.overview || "";
    h.title = j.title || "";
    return h;
  }

  function load(t) {
    if (cache[t.key]) return Promise.resolve(cache[t.key]);
    var p;
    if (t.kind === "movie") {
      p = get("/api/tv/movie/" + t.id).then(function (j) {
        var h = fromMedia(j, { parts: [] });
        if (j.year) h.parts.push(j.year);
        var d = minutes(j.duration); if (d) h.parts.push(d);
        h.sub = j.tagline || "";
        return h;
      });
    } else if (t.kind === "collection") {
      p = get("/api/tv/collection/" + t.id).then(function (j) {
        var n = (j.items || []).length;
        return { bd: j.backdrop || "", logo: j.logo || "", rating: "", overview: j.overview || "", title: j.title || "", sub: "",
                 parts: [Tn("home.collection_n", n)] };
      });
    } else {
      var epId = t.kind === "episode" ? t.id : t.ep;
      var ep = epId ? get("/api/tv/episode/" + epId).catch(function () { return null; }) : Promise.resolve(null);
      p = ep.then(function (e) {
        var sid = t.kind === "episode" ? (e && e.media_id) : t.id;
        if (!sid) throw 0;
        return get("/api/tv/show/" + sid).then(function (j) {
          var h = fromMedia(j, { parts: [] });
          if (e) {
            h.parts.push(T("home.season_episode", { s: e.season, e: e.episode }));
            var dt = dateBr(e.air_date); if (dt) h.parts.push(dt);
            var d = minutes(e.duration); if (d) h.parts.push(d);
            h.sub = e.title || "";
            if (e.overview) h.overview = e.overview;
          } else {
            if (j.year) h.parts.push(j.year);
            h.sub = j.tagline || "";
          }
          return h;
        });
      });
    }
    return p.then(function (h) { cache[t.key] = h; return h; });
  }

  function apply(h) {
    sfHeroBg.set(h.bd || "");
    title.textContent = h.title || "";
    logo.hidden = true;
    title.hidden = false;
    if (h.logo) {
      logo.onload = function () { logo.hidden = false; title.hidden = true; };
      logo.onerror = function () { logo.hidden = true; title.hidden = false; };
      logo.alt = h.title || "";
      logo.src = h.logo;
    }
    sub.textContent = h.sub || "";
    meta.textContent = (h.parts || []).join("  ");
    rate.hidden = !h.rating;
    rate.textContent = h.rating || "";
    ov.textContent = h.overview || "";
  }

  var seq = 0;
  function show(t) {
    var mine = ++seq;
    return load(t).then(function (h) { if (mine !== seq) return; current = t.key; apply(h); });
  }
  function blank() { seq++; current = ""; apply({}); }
  function firstCard(scope) { return scope.querySelector(".pcard:not(.pcard-ghost)"); }
  function firstHero(scope) {
    clearTimeout(timer);
    var c = firstCard(scope), t = c && target(c);
    if (!t) { blank(); return; }
    if (t.key === current) return;
    show(t).catch(function () { sfHeroBg.set(""); });
  }

  function focusCard(card) {
    var t = target(card);
    if (!t || t.key === current) return;
    clearTimeout(timer);
    timer = setTimeout(function () {
      show(t).catch(function () { /* sem destaque: mantém o anterior */ });
    }, 350);
  }

  var rows = document.querySelector(".content");
  rows.addEventListener("mouseover", function (e) { var c = e.target.closest && e.target.closest(".pcard"); if (c) focusCard(c); });
  rows.addEventListener("focusin", function (e) { var c = e.target.closest && e.target.closest(".pcard"); if (c) focusCard(c); });

  // primeiro item: o 1º cartão da página (como a TV, que começa no 1º da 1ª fileira)
  firstHero(rows);

  /* ---- 56.4: abas Explorar e Coleções (só no Início; na biblioteca as pílulas são links, 56.5) ---- */
  var alt = $("tvh-alt");
  if (alt) (function () {
  var tabs = box.querySelectorAll(".tvh-tab"), tab = "rec", libsP = null, loaded = {};
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c]; }); }

  function cardHtml(c) {
    var id = c.id, t = c.type, href, attrs = "", wide = false, sub = c.sub || "", cls = "";
    if (t === "collection") { href = "/collection/" + id; attrs = ' data-collection="' + id + '"'; sub = Tn("common.items", c.n || 0); }
    else if (t === "video") { href = "/watch/movie/" + id; wide = true; sub = ""; }
    else if (t === "show") { href = "/show/" + id; cls = " pcard-t-show"; }
    else { href = "/movie/" + id; cls = " pcard-t-movie"; }
    var title = c.title || "";
    return '<div class="pcard' + (wide ? " pcard-wide" : "") + cls + '"' + attrs + '><div class="pcard-poster">' +
      '<span class="pcard-ph" aria-hidden="true">' + esc(title) + '</span>' +
      '<a class="pcard-link" href="' + esc(href) + '" tabindex="-1" aria-hidden="true"><img src="' + esc(c.image) + '" alt="" loading="lazy" onerror="this.remove()"></a>' +
      (c.watched ? '<span class="pcard-seen" title="' + esc(T("card.watched")) + '"><svg class="ic ic-sm"><use href="#i-check"/></svg></span>' : "") +
      (c.pct ? '<span class="pcard-bar"><i style="width: ' + Math.min(100, Math.round(c.pct)) + '%"></i></span>' : "") +
      '<div class="pcard-over"><a class="pcard-play" href="' + esc(href) + '" aria-label="' + esc(T("card.play")) + '"><svg class="ic ic-lg"><use href="#i-play"/></svg></a></div></div>' +
      '<div class="pcard-txt"><a class="pcard-title" href="' + esc(href) + '" title="' + esc(title) + '">' + esc(title) + '</a>' +
      (sub ? '<div class="pcard-sub pcard-sub1">' + esc(sub) + '</div>' : "") + '</div></div>';
  }
  function sectionHtml(r) {
    return '<section class="carousel tvh-x" data-row="' + esc(r.key) + '"><div class="carousel-head"><h2 class="section-title">' + esc(r.title) + '</h2>' +
      '<div class="carousel-arrows"><button type="button" class="carousel-btn" data-dir="-1" aria-label="' + esc(T("common.prev")) + '"><svg class="ic"><use href="#i-chevron-left"/></svg></button>' +
      '<button type="button" class="carousel-btn" data-dir="1" aria-label="' + esc(T("common.next")) + '"><svg class="ic"><use href="#i-chevron-right"/></svg></button></div></div>' +
      '<div class="carousel-track">' + r.items.map(cardHtml).join("") + '</div></section>';
  }

  function getLibs() {
    return libsP || (libsP = get("/api/tv/libraries").then(function (j) { return j.libraries || []; }).catch(function () { return []; }));
  }
  function loadExp() {
    return loaded.exp || (loaded.exp = getLibs().then(function (ls) {
      return Promise.all(ls.map(function (l) {
        return get("/api/tv/library/" + l.id + "?limit=40").then(function (j) { return { key: "x:" + l.id, title: l.name, items: (j.items || []).slice(0, 40) }; }).catch(function () { return null; });
      }));
    }).then(function (a) { return a.filter(function (r) { return r && r.items.length; }); }));
  }
  function loadCol() {
    return loaded.col || (loaded.col = getLibs().then(function (ls) {
      return Promise.all(ls.map(function (l) {
        return get("/api/tv/library/" + l.id + "/collections").then(function (j) { return { key: "c:" + l.id, title: T("home.collections_in", { name: l.name }), items: j.items || [] }; }).catch(function () { return null; });
      }));
    }).then(function (a) { return a.filter(function (r) { return r && r.items.length; }); }));
  }

  function render(name, list) {
    if (!list.length) {
      alt.innerHTML = '<div class="tvh-msg">' + (name === "col" ? T("home.no_collections") : T("home.nothing_yet")) + '</div>';
      blank();
      return;
    }
    alt.innerHTML = list.map(sectionHtml).join("");
    alt.querySelectorAll(".carousel").forEach(function (c) { if (window.sfCarousel) window.sfCarousel.init(c); });
    firstHero(alt);
  }

  function showTab(name) {
    tab = name;
    tabs.forEach(function (b) { var on = b.dataset.tab === name; b.classList.toggle("on", on); b.setAttribute("aria-selected", on ? "true" : "false"); });
    document.body.classList.toggle("tvh-altmode", name !== "rec");
    alt.hidden = name === "rec";
    alt.innerHTML = "";
    if (name === "rec") { firstHero(rows); return; }
    alt.innerHTML = '<div class="tvh-msg">' + esc(T("common.loading")) + '</div>';
    (name === "exp" ? loadExp() : loadCol()).then(function (list) { if (tab === name) render(name, list); });
  }
  tabs.forEach(function (b) { b.addEventListener("click", function () { if (b.dataset.tab !== tab) showTab(b.dataset.tab); }); });

  // aba sem dado não aparece: Explorar quando há biblioteca; Coleções quando alguma biblioteca tem coleção
  var tExp = box.querySelector('[data-tab="exp"]'), tCol = box.querySelector('[data-tab="col"]');
  getLibs().then(function (ls) { tExp.hidden = !ls.length; });
  loadCol().then(function (list) { tCol.hidden = !list.length; });

  })();

})();
