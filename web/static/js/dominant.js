/* 56.1: cor dominante do backdrop e fundo do destaque (mesma conta do app da TV: HeroBackdrop/dominantColor).
   API: sfHeroBg.set(url) troca o fundo (imagem no canto superior direito + cor vibrante); sfHeroBg.clear(); sfHeroBg.dominant(url) -> Promise<[r,g,b]> */
(function () {
  var DEF = [31, 35, 38];            // #1f2326, a cor neutra da TV
  var cache = {};

  function rgb2hsv(r, g, b) {
    r /= 255; g /= 255; b /= 255;
    var mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn, h = 0;
    if (d > 0) {
      if (mx === r) h = ((g - b) / d) % 6;
      else if (mx === g) h = (b - r) / d + 2;
      else h = (r - g) / d + 4;
      h *= 60; if (h < 0) h += 360;
    }
    return [h, mx === 0 ? 0 : d / mx, mx];
  }

  function hsv2rgb(h, s, v) {
    var c = v * s, x = c * (1 - Math.abs((h / 60) % 2 - 1)), m = v - c, r = 0, g = 0, b = 0;
    if (h < 60) { r = c; g = x; } else if (h < 120) { r = x; g = c; } else if (h < 180) { g = c; b = x; }
    else if (h < 240) { g = x; b = c; } else if (h < 300) { r = x; b = c; } else { r = c; b = x; }
    return [Math.round((r + m) * 255), Math.round((g + m) * 255), Math.round((b + m) * 255)];
  }

  /* agrupa os pixels (64x36) por matiz em 24 faixas de 15°, pesa por saturação x brilho, ignora cinzas e escuros;
     a faixa mais pesada vira a cor, com saturação >= 0,6 e brilho entre 0,5 e 0,78 */
  function compute(img) {
    var cv = document.createElement("canvas"), W = 64, H = 36;
    cv.width = W; cv.height = H;
    var cx = cv.getContext("2d", { willReadFrequently: true });
    cx.drawImage(img, 0, 0, W, H);
    var d = cx.getImageData(0, 0, W, H).data;
    var w = [], r = [], g = [], b = [], i, k;
    for (k = 0; k < 24; k++) { w[k] = 0; r[k] = 0; g[k] = 0; b[k] = 0; }
    for (i = 0; i < d.length; i += 4) {
      var hsv = rgb2hsv(d[i], d[i + 1], d[i + 2]);
      if (hsv[1] < 0.25 || hsv[2] < 0.25) continue;
      k = Math.min(23, Math.max(0, Math.floor(hsv[0] / 15)));
      var wt = hsv[1] * hsv[2];
      w[k] += wt; r[k] += wt * d[i]; g[k] += wt * d[i + 1]; b[k] += wt * d[i + 2];
    }
    var best = -1;
    for (k = 0; k < 24; k++) if (w[k] > 1 && (best < 0 || w[k] > w[best])) best = k;
    if (best < 0) return null;
    var h = rgb2hsv(Math.floor(r[best] / w[best]), Math.floor(g[best] / w[best]), Math.floor(b[best] / w[best]));
    return hsv2rgb(h[0], Math.max(h[1], 0.6), Math.min(0.78, Math.max(0.5, h[2])));
  }

  function dominant(url) {
    return new Promise(function (resolve) {
      if (!url) { resolve(DEF); return; }
      if (cache[url]) { resolve(cache[url]); return; }
      var img = new Image();
      img.onload = function () {
        var c = null;
        try { c = compute(img); } catch (e) { c = null; }
        cache[url] = c || DEF;
        resolve(cache[url]);
      };
      img.onerror = function () { resolve(DEF); };
      img.src = url;
    });
  }

  /* ---- fundo do destaque ---- */
  var root = null, layers = [], cur = 0, token = 0;

  function ensure() {
    if (root) return;
    root = document.createElement("div");
    root.className = "hero-bg";
    root.setAttribute("aria-hidden", "true");
    root.innerHTML = '<div class="hero-bg-fill"></div><div class="hero-bg-shade"></div><div class="hero-bg-img"></div><div class="hero-bg-img"></div>';
    document.body.insertBefore(root, document.body.firstChild);
    layers = root.querySelectorAll(".hero-bg-img");
  }

  function setColor(c) {
    root.querySelector(".hero-bg-fill").style.backgroundColor = "rgb(" + c[0] + "," + c[1] + "," + c[2] + ")";
  }

  function set(url) {
    ensure();
    var my = ++token;
    document.body.classList.add("has-hero-bg");
    if (!url) { setColor(DEF); layers[0].classList.remove("on"); layers[1].classList.remove("on"); return; }
    dominant(url).then(function (c) {
      if (my !== token) return;
      setColor(c);
      var next = layers[1 - cur], old = layers[cur];
      var im = new Image();
      im.onload = function () {
        if (my !== token) return;
        next.style.backgroundImage = "url(\"" + url + "\")";
        next.classList.add("on");
        old.classList.remove("on");
        cur = 1 - cur;
      };
      im.src = url;
    });
  }

  function clear() {
    token++;
    if (root) { root.remove(); root = null; layers = []; cur = 0; }
    document.body.classList.remove("has-hero-bg");
  }

  window.sfHeroBg = { set: set, clear: clear, dominant: dominant, DEFAULT: DEF };
})();
