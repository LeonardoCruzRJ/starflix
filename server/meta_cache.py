"""59.41: metadados de cada idioma usado ficam guardados (tabela meta_cache + cópias das imagens em data/posters/_lang/<idioma>/)
e são reaproveitados quando o usuário volta a um idioma já usado: só o que nunca foi buscado naquele idioma é buscado de novo.
Campos travados (locks) nunca são tocados. Cada filme/série leva em media.data_lang o idioma em que seus dados foram gravados."""
import json
import os
import shutil

import config

LIBS = "(SELECT id FROM libraries WHERE type IN ('movie', 'show'))"
MEDIA_COLS = ("overview", "genres", "tagline", "poster", "backdrop", "logo")  # + title nos filmes (na série o título é a chave dos episódios)
IMG_COLS = ("poster", "backdrop", "logo")


def _lk(raw):
    try:
        v = json.loads(raw) if raw else {}
    except ValueError:
        v = {}
    return v if isinstance(v, dict) else {}


def _safe(rel):
    if not rel or rel.startswith("/"):
        return None
    n = os.path.normpath(rel)
    return None if os.path.isabs(n) or n.startswith("..") else n


def _stash(rel, lang):
    n = _safe(rel)
    if n and os.path.isfile(os.path.join(config.POSTERS_DIR, n)):
        dst = os.path.join(config.POSTERS_DIR, "_lang", lang, n)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(config.POSTERS_DIR, n), dst)


def _has_stash(rel, lang):
    n = _safe(rel)
    return n is None or os.path.isfile(os.path.join(config.POSTERS_DIR, "_lang", lang, n))


def _unstash(rel, lang):
    n = _safe(rel)
    if n:
        dst = os.path.join(config.POSTERS_DIR, n)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(config.POSTERS_DIR, "_lang", lang, n), dst)


def _put(conn, lang, kind, ref, data):
    conn.execute("INSERT INTO meta_cache (lang, kind, ref, data) VALUES (?, ?, ?, ?) ON CONFLICT(lang, kind, ref) DO UPDATE SET data = excluded.data",
                 (lang, kind, ref, json.dumps(data, ensure_ascii=False)))


def save(conn, legacy, new):
    """Guarda, no idioma em que foram gravados, os dados completos (meta_ok = 1) que NÃO estão no idioma `new`."""
    rows = conn.execute(
        "SELECT id, path, title, overview, genres, tagline, poster, backdrop, logo, COALESCE(data_lang, ?) AS dl FROM media "
        f"WHERE tmdb_id > 0 AND meta_ok = 1 AND library_id IN {LIBS} AND COALESCE(data_lang, ?) != ?", (legacy, legacy, new)).fetchall()
    for r in rows:
        dl = r["dl"]
        d = {c: r[c] for c in MEDIA_COLS}
        if r["path"] is not None:
            d["title"] = r["title"]
        for k in ("genre", "country"):
            d["tag_" + k] = [x[0] for x in conn.execute("SELECT name FROM tags WHERE media_id = ? AND kind = ?", (r["id"], k))]
        for c in IMG_COLS:
            _stash(r[c], dl)
        _put(conn, dl, "media", r["id"], d)
        for s in conn.execute("SELECT id, title, overview, poster FROM seasons WHERE media_id = ?", (r["id"],)):
            _stash(s["poster"], dl)
            _put(conn, dl, "season", s["id"], {"title": s["title"], "overview": s["overview"], "poster": s["poster"]})
        for e in conn.execute("SELECT id, title, overview FROM episodes WHERE media_id = ? AND title IS NOT NULL", (r["id"],)):
            _put(conn, dl, "episode", e["id"], {"title": e["title"], "overview": e["overview"]})
    return len(rows)


def restore(conn, legacy, new):
    """Devolve ao banco os dados já guardados em `new` para os itens que não estão nesse idioma. Devolve {media_id restaurados}."""
    done = set()
    rows = conn.execute(
        "SELECT m.id, m.path, m.locks, c.data FROM media m JOIN meta_cache c ON c.lang = ? AND c.kind = 'media' AND c.ref = m.id "
        f"WHERE m.tmdb_id > 0 AND m.library_id IN {LIBS} AND COALESCE(m.data_lang, ?) != ?", (new, legacy, new)).fetchall()
    for r in rows:
        d, lk = json.loads(r["data"]), _lk(r["locks"])
        if not all(_has_stash(d.get(c), new) for c in IMG_COLS if not lk.get(c)):
            continue  # imagem local guardada sumiu: este item é buscado de novo
        sets, vals = [], []
        for c in (("title",) if r["path"] is not None and "title" in d else ()) + MEDIA_COLS:
            if lk.get(c):
                continue
            if c in IMG_COLS:
                _unstash(d.get(c), new)
            sets.append(f"{c} = ?")
            vals.append(d.get(c))
        sets += ["meta_ok = 1", "data_lang = ?"]
        vals.append(new)
        conn.execute(f"UPDATE media SET {', '.join(sets)} WHERE id = ?", (*vals, r["id"]))
        for k in ("genre", "country"):
            if not lk.get("genres" if k == "genre" else "country"):
                conn.execute("DELETE FROM tags WHERE media_id = ? AND kind = ?", (r["id"], k))
                for n in d.get("tag_" + k) or []:
                    conn.execute("INSERT OR IGNORE INTO tags (media_id, kind, name) VALUES (?, ?, ?)", (r["id"], k, n))
        for s in conn.execute("SELECT s.id, s.locks, c.data FROM seasons s JOIN meta_cache c ON c.lang = ? AND c.kind = 'season' AND c.ref = s.id "
                              "WHERE s.media_id = ?", (new, r["id"])).fetchall():
            sd, sl = json.loads(s["data"]), _lk(s["locks"])
            if not sl.get("poster") and not _has_stash(sd.get("poster"), new):
                continue
            for c in ("title", "overview", "poster"):
                if sl.get(c):
                    continue
                if c == "poster":
                    _unstash(sd.get(c), new)
                conn.execute(f"UPDATE seasons SET {c} = ? WHERE id = ?", (sd.get(c), s["id"]))
        for e in conn.execute("SELECT e.id, e.locks, c.data FROM episodes e JOIN meta_cache c ON c.lang = ? AND c.kind = 'episode' AND c.ref = e.id "
                              "WHERE e.media_id = ?", (new, r["id"])).fetchall():
            ed, el = json.loads(e["data"]), _lk(e["locks"])
            for c in ("title", "overview"):
                if not el.get(c):
                    conn.execute(f"UPDATE episodes SET {c} = ? WHERE id = ?", (ed.get(c), e["id"]))
        done.add(r["id"])
    return done
