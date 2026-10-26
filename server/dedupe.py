"""35.3: um só item por filme. Linhas de `media` do mesmo filme (mesmo tmdb_id; sem correspondência, mesmo título e ano)
viram uma; os arquivos repetidos ficam em `media_dups` para o scanner não os readicionar."""
import re
import unicodedata

from server.db import get_db


def _key(r):
    if (r["tmdb_id"] or 0) > 0:
        return ("tmdb", r["tmdb_id"])
    if r["tmdb_id"] is None:  # ainda não buscado: não casa com ninguém
        return None
    t = unicodedata.normalize("NFKD", r["title"] or "").casefold()
    t = re.sub(r"[\W_]+", "", t)
    return ("name", t, r["year"]) if t else None


def _merge_progress(conn, keep, dup):
    for p in conn.execute("SELECT * FROM progress WHERE item_type = 'movie' AND item_id = ?", (dup,)).fetchall():
        k = conn.execute("SELECT updated_at FROM progress WHERE profile_id = ? AND item_type = 'movie' AND item_id = ?",
                         (p["profile_id"], keep)).fetchone()
        if k is None or (p["updated_at"] or "") > (k["updated_at"] or ""):
            conn.execute("INSERT OR REPLACE INTO progress (profile_id, item_type, item_id, position, watched, updated_at) "
                         "VALUES (?, 'movie', ?, ?, ?, ?)", (p["profile_id"], keep, p["position"], p["watched"], p["updated_at"]))
    conn.execute("DELETE FROM progress WHERE item_type = 'movie' AND item_id = ?", (dup,))


def merge_movies(library_id, prefer=None):
    """Une os filmes duplicados da biblioteca; `prefer` (id) é o item que fica no grupo dele. Devolve quantos foram unidos."""
    from server import metadata  # import tardio: metadata não importa este módulo
    merged, names = 0, []
    with get_db() as conn:
        lib = conn.execute("SELECT type FROM libraries WHERE id = ?", (library_id,)).fetchone()
        if not lib or lib["type"] != "movie":
            return 0
        groups = {}
        for r in conn.execute("SELECT id, title, year, tmdb_id, path FROM media WHERE library_id = ? AND path IS NOT NULL "
                              "ORDER BY id", (library_id,)):
            k = _key(r)
            if k:
                groups.setdefault(k, []).append(r)
        for rows in groups.values():
            if len(rows) < 2:
                continue
            keep = next((r for r in rows if r["id"] == prefer), rows[0])
            for d in rows:
                if d["id"] == keep["id"]:
                    continue
                conn.execute("INSERT OR IGNORE INTO media_dups (path, media_id) VALUES (?, ?)", (d["path"], keep["id"]))
                conn.execute("UPDATE media_dups SET media_id = ? WHERE media_id = ?", (keep["id"], d["id"]))
                _merge_progress(conn, keep["id"], d["id"])
                for tbl in ("my_list", "collection_items", "playlist_items"):
                    conn.execute(f"UPDATE OR IGNORE {tbl} SET media_id = ? WHERE media_id = ?", (keep["id"], d["id"]))
                conn.execute("UPDATE OR IGNORE stars SET item_id = ? WHERE item_type = 'movie' AND item_id = ?", (keep["id"], d["id"]))
                conn.execute("DELETE FROM stars WHERE item_type = 'movie' AND item_id = ?", (d["id"],))
                names += [x[0] for x in conn.execute("SELECT poster FROM media WHERE id = ? UNION ALL SELECT backdrop FROM media "
                                                     "WHERE id = ? UNION ALL SELECT logo FROM media WHERE id = ?",
                                                     (d["id"], d["id"], d["id"]))]
                conn.execute("DELETE FROM media WHERE id = ?", (d["id"],))
                conn.commit()
                merged += 1
    keep_names = set()
    with get_db() as conn:
        for r in conn.execute("SELECT poster, backdrop, logo FROM media WHERE library_id = ?", (library_id,)):
            keep_names.update(r)
    for n in names:
        if n and n not in keep_names:
            metadata.remove_local(n)
    if merged:
        metadata.prune_people()
    return merged


def _merge_ep_progress(conn, keep, dup):
    for p in conn.execute("SELECT * FROM progress WHERE item_type = 'episode' AND item_id = ?", (dup,)).fetchall():
        k = conn.execute("SELECT updated_at FROM progress WHERE profile_id = ? AND item_type = 'episode' AND item_id = ?",
                         (p["profile_id"], keep)).fetchone()
        if k is None or (p["updated_at"] or "") > (k["updated_at"] or ""):
            conn.execute("INSERT OR REPLACE INTO progress (profile_id, item_type, item_id, position, watched, updated_at) "
                         "VALUES (?, 'episode', ?, ?, ?, ?)", (p["profile_id"], keep, p["position"], p["watched"], p["updated_at"]))
    conn.execute("DELETE FROM progress WHERE item_type = 'episode' AND item_id = ?", (dup,))


def _dedupe_episodes(conn, mid):
    """Um só episódio por (temporada, episódio) na série; o arquivo repetido vai para media_dups (o scanner o usa de volta
    se o arquivo escolhido sumir). Devolve quantos foram unidos."""
    seen, n = {}, 0
    for e in conn.execute("SELECT id, season, episode, path FROM episodes WHERE media_id = ? ORDER BY id", (mid,)).fetchall():
        k = (e["season"], e["episode"])
        if k not in seen:
            seen[k] = e
            continue
        keep = seen[k]
        if e["path"] != keep["path"]:
            conn.execute("INSERT OR IGNORE INTO media_dups (path, media_id) VALUES (?, ?)", (e["path"], mid))
        _merge_ep_progress(conn, keep["id"], e["id"])
        conn.execute("DELETE FROM episodes WHERE id = ?", (e["id"],))
        n += 1
    return n


def merge_shows(library_id, prefer=None):
    """Une as séries duplicadas da biblioteca (mesmo tmdb_id; sem correspondência, mesmo título e ano) e os episódios
    repetidos. `prefer` (id) é a série que fica no grupo dela. Devolve quantas séries/episódios foram unidos."""
    from server import metadata
    merged, names = 0, []
    with get_db() as conn:
        lib = conn.execute("SELECT type FROM libraries WHERE id = ?", (library_id,)).fetchone()
        if not lib or lib["type"] != "show":
            return 0
        groups = {}
        for r in conn.execute("SELECT id, title, year, tmdb_id FROM media WHERE library_id = ? AND path IS NULL ORDER BY id",
                              (library_id,)):
            k = _key(r)
            if k:
                groups.setdefault(k, []).append(r)
        for rows in groups.values():
            if len(rows) < 2:
                continue
            keep = next((r for r in rows if r["id"] == prefer), rows[0])["id"]
            for d in rows:
                if d["id"] == keep:
                    continue
                conn.execute("UPDATE episodes SET media_id = ? WHERE media_id = ?", (keep, d["id"]))
                conn.execute("UPDATE media_dups SET media_id = ? WHERE media_id = ?", (keep, d["id"]))
                for tbl in ("my_list", "collection_items", "playlist_items"):
                    conn.execute(f"UPDATE OR IGNORE {tbl} SET media_id = ? WHERE media_id = ?", (keep, d["id"]))
                conn.execute("UPDATE OR IGNORE stars SET item_id = ? WHERE item_type = 'show' AND item_id = ?", (keep, d["id"]))
                conn.execute("DELETE FROM stars WHERE item_type = 'show' AND item_id = ?", (d["id"],))
                names += [x[0] for x in conn.execute("SELECT poster FROM media WHERE id = ? UNION ALL SELECT backdrop FROM media "
                                                     "WHERE id = ? UNION ALL SELECT logo FROM media WHERE id = ?",
                                                     (d["id"], d["id"], d["id"]))]
                names += metadata.show_image_names(conn, "m.id = ?", (d["id"],))
                conn.execute("DELETE FROM media WHERE id = ?", (d["id"],))
                merged += 1
            conn.commit()
        for r in conn.execute("SELECT id FROM media WHERE library_id = ? AND path IS NULL", (library_id,)).fetchall():
            merged += _dedupe_episodes(conn, r["id"])
        conn.commit()
    keep_names = set()
    with get_db() as conn:
        for r in conn.execute("SELECT poster, backdrop, logo FROM media WHERE library_id = ?", (library_id,)):
            keep_names.update(r)
        keep_names.update(n for n in metadata.show_image_names(conn, "m.library_id = ?", (library_id,)))
    for n in names:
        if n and n not in keep_names:
            metadata.remove_local(n)
    if merged:
        metadata.prune_people()
    return merged
