/* 52.3: perfil de capacidades do navegador (?caps=v=…&a=…&c=…&b10=…&hdr=…&ch=…) enviado em todo /play. */
(function () {
  'use strict';
  var KEY = 'sf_caps', v = document.createElement('video'), a = document.createElement('audio');
  var MS = window.MediaSource || window.ManagedMediaSource;
  function can(el, t) { try { return !!el.canPlayType(t); } catch (e) { return false; } }
  function ms(t) { try { return !!(MS && MS.isTypeSupported && MS.isTypeSupported(t)); } catch (e) { return false; } }
  function vok(c, t) { return can(v, t) || ms(t); }

  var caps = { v: [], a: [], c: [], b10: false, hdr: false, ch: 8 };
  function build() {
    var h264 = vok('h264', 'video/mp4; codecs="avc1.640028"');
    var hevc = vok('hevc', 'video/mp4; codecs="hvc1.1.6.L93.B0"') || ms('video/mp4; codecs="hvc1.2.4.L153.B0"');
    var av1 = vok('av1', 'video/mp4; codecs="av01.0.05M.08"');
    var vp9 = vok('vp9', 'video/webm; codecs="vp9"');
    caps.v = [h264 && 'h264', hevc && 'hevc', av1 && 'av1', vp9 && 'vp9'].filter(Boolean);
    caps.b10 = ms('video/mp4; codecs="hvc1.2.4.L153.B0"') || ms('video/mp4; codecs="av01.0.08M.10"');
    caps.a = [
      (can(a, 'audio/mp4; codecs="mp4a.40.2"') || can(a, 'audio/aac')) && 'aac',
      can(a, 'audio/mpeg') && 'mp3',
      can(a, 'audio/webm; codecs="opus"') && 'opus',
      can(a, 'audio/ogg; codecs="vorbis"') && 'vorbis',
      (can(a, 'audio/flac') || ms('audio/mp4; codecs="flac"')) && 'flac',
      ms('audio/mp4; codecs="ac-3"') && 'ac3',
      ms('audio/mp4; codecs="ec-3"') && 'eac3'
    ].filter(Boolean);
    caps.c = [
      h264 && 'mp4',
      (can(v, 'video/x-matroska') || can(v, 'video/webm')) && (can(v, 'video/x-matroska') ? 'mkv' : null),
      can(v, 'video/webm') && 'webm',
      can(v, 'video/mp2t') && 'ts'
    ].filter(Boolean);
    try { caps.hdr = !!(window.matchMedia && matchMedia('(dynamic-range: high)').matches); } catch (e) { caps.hdr = false; }
  }

  function save() { try { localStorage.setItem(KEY, JSON.stringify(caps)); } catch (e) {} }

  // MediaCapabilities refina HEVC/AV1: só conta `supported` com `powerEfficient` ou `smooth`.
  function refine() {
    var mc = navigator.mediaCapabilities;
    if (!mc || !mc.decodingInfo) return Promise.resolve();
    function test(codec, contentType) {
      var cfg = { type: 'media-source', video: { contentType: contentType, width: 1920, height: 1080, bitrate: 8000000, framerate: 24 } };
      return mc.decodingInfo(cfg).then(function (r) { return !!(r.supported && (r.powerEfficient || r.smooth)); }, function () { return null; });
    }
    var jobs = [];
    [['hevc', 'video/mp4; codecs="hvc1.1.6.L93.B0"'], ['av1', 'video/mp4; codecs="av01.0.05M.08"']].forEach(function (p) {
      if (caps.v.indexOf(p[0]) < 0) return;
      jobs.push(test(p[0], p[1]).then(function (ok) { if (ok === false) caps.v = caps.v.filter(function (x) { return x !== p[0]; }); }));
    });
    if (caps.b10) {
      jobs.push(test('hevc10', 'video/mp4; codecs="hvc1.2.4.L153.B0"').then(function (ok) {
        if (ok === false) test('av110', 'video/mp4; codecs="av01.0.08M.10"').then(function (ok2) { if (ok2 !== true) { caps.b10 = false; save(); } });
      }));
    }
    return Promise.all(jobs);
  }

  build();
  var ready = Promise.race([refine(), new Promise(function (r) { setTimeout(r, 1500); })]).then(save, save);

  window.SFCaps = {
    ready: ready,
    get: function () {
      var j = function (x) { return x.join('.'); };
      return 'v=' + j(caps.v) + '&a=' + j(caps.a) + '&c=' + j(caps.c) + '&b10=' + (caps.b10 ? 1 : 0) + '&hdr=' + (caps.hdr ? 1 : 0) + '&ch=' + caps.ch;
    }
  };
})();
