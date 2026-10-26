// 46.4: menu ⋮ na página do filme/série (ao lado do nome da biblioteca): os comandos do menu da biblioteca, só para este item.
// Sem Desafixar, Conceder Acesso e Esvaziar Lixeira. Só admin; só na web.
(window.SF_I18N ? SF_I18N.ready : Promise.resolve()).then(function () {
  var btn = document.querySelector('[data-item-menu]');
  if (!btn) return;
  var p = btn.dataset.itemMenu.split(':'), kind = p[0], ref = p[1], name = btn.dataset.itemName || '';
  var mv = kind === 'movie';

  function act(a) {
    return function () { if (window.sfItemAction) window.sfItemAction({act: a, kind: kind, ref: ref, name: name}); };
  }

  function items() {
    return [
      {l: T(mv ? 'im.examine_movie' : 'im.examine_show'), fn: act('examine')},
      {l: T(mv ? 'im.manage_movie' : 'im.manage_show'), sub: [
        {l: T('lib.edit'), fn: function () { if (window.sfEditOpen) window.sfEditOpen(kind, ref); }},
        {l: T('lib.refresh_all'), fn: act('refresh')},
        {l: T('lib.analyze'), fn: act('analyze')},
        {l: T('lib.gen_thumbs'), fn: act('trickplay')},
        {l: T('im.optimize'), fn: act('optimize')},
        {l: T('im.unoptimize'), fn: act('unoptimize')},
        {l: T('lib.delete'), fn: act('delete')}
      ]}
    ];
  }

  // stopPropagation: o clique no documento (menu.js) fecharia o menu recém-aberto
  btn.addEventListener('click', function (e) {
    e.stopPropagation();
    if (window.sfMenuAt) window.sfMenuAt(btn, items(), e.detail === 0, 'ctx-compact');
  });
});
