// Cards de pôster (23.3): ○ marca/desmarca assistido (filme/episódio) e recarrega a página.
document.addEventListener('click', async function (e) {
  var b = e.target.closest('.pcard-sel');
  if (!b) return;
  var card = b.closest('.pcard');
  if (!card || !card.dataset.kind || !card.dataset.id) return;
  e.preventDefault();
  b.disabled = true;
  try {
    var r = await fetch('/progress/' + card.dataset.kind + '/' + card.dataset.id + '/watched', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({watched: b.dataset.watched})
    });
    if (r.status === 401) { location.href = '/login'; return; }
    location.reload();
  } catch (err) { b.disabled = false; }
});
