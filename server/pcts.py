"""35.20: percentual assistido por item (barra amarela sob a capa) — filmes/vídeos pela posição, séries pelos episódios."""
import json

from server.progress import RESUME_MIN


def _dur(info):
    try:
        return (json.loads(info) if info else {}).get("duration") or 0
    except ValueError:
        return 0


def pct_map(conn, pid, ids):
    """{media_id: pct} só para quem está em andamento (0 < pct < 100)."""
    ids = [int(i) for i in ids]
    out = {}
    for k in range(0, len(ids), 500):
        part = ids[k:k + 500]
        ph = ",".join("?" * len(part))
        for r in conn.execute(
            f"SELECT m.id, m.info, p.position, p.watched FROM media m LEFT JOIN progress p ON p.profile_id = ? "
            f"AND p.item_type = 'movie' AND p.item_id = m.id WHERE m.id IN ({ph}) AND m.path IS NOT NULL", (pid, *part)):
            d = _dur(r["info"])
            if d and not r["watched"] and (r["position"] or 0) > RESUME_MIN:
                out[r["id"]] = min(99.0, r["position"] / d * 100)
        tot, seen = {}, {}
        for r in conn.execute(
            f"SELECT e.media_id, COALESCE(p.watched, 0) AS w FROM episodes e LEFT JOIN progress p ON p.profile_id = ? "
            f"AND p.item_type = 'episode' AND p.item_id = e.id WHERE e.media_id IN ({ph})", (pid, *part)):
            tot[r["media_id"]] = tot.get(r["media_id"], 0) + 1
            seen[r["media_id"]] = seen.get(r["media_id"], 0) + (1 if r["w"] else 0)
        for mid, t in tot.items():
            if 0 < seen[mid] < t:
                out[mid] = seen[mid] / t * 100
    return out
