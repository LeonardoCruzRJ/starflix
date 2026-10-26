/* 31.5: fila de reprodução por perfil (localStorage "sf.queue", sem servidor).
   sfQueue.add(items) = Adicionar à fila · sfQueue.next(items) = Reproduzir a seguir (vai para o início)
   items: [{k: 'movie'|'episode', id: N}] · sfQueue.shift() tira e devolve o primeiro · sfQueue.url(item) */
(function () {
  var KEY = 'sf.queue', MAX = 200;
  function pid() { return document.documentElement.dataset.pid || ''; }
  function valid(x) { return x && (x.k === 'movie' || x.k === 'episode') && Number.isInteger(x.id) && x.id > 0; }
  function all() {
    try { var o = JSON.parse(localStorage.getItem(KEY) || '{}'); return o && typeof o === 'object' && !Array.isArray(o) ? o : {}; }
    catch (e) { return {}; }
  }
  function get() { var l = all()[pid()]; return Array.isArray(l) ? l.filter(valid) : []; }
  function save(l) {
    try {
      var o = all();
      if (l.length) o[pid()] = l.slice(0, MAX); else delete o[pid()];
      localStorage.setItem(KEY, JSON.stringify(o));
    } catch (e) {}
  }
  function clean(items) {
    var seen = {}, out = [];
    (items || []).forEach(function (x) {
      if (!valid(x)) return;
      var key = x.k + ':' + x.id;
      if (!seen[key]) { seen[key] = 1; out.push({ k: x.k, id: x.id }); }
    });
    return out;
  }
  function merge(first, second) { return clean(first.concat(second)); }
  window.sfQueue = {
    get: get,
    size: function () { return get().length; },
    add: function (items) { var l = merge(get(), clean(items)); save(l); return l.length; },
    next: function (items) { var l = merge(clean(items), get()); save(l); return l.length; },
    shift: function () { var l = get(), x = l.shift(); save(l); return x || null; },
    clear: function () { save([]); },
    url: function (x) { return '/watch/' + x.k + '/' + x.id; }
  };
})();
