import difflib
import json
import re

from flask import Blueprint, jsonify, render_template, request, session

from server.pcts import pct_map
from server.auth import login_required
from server.db import fold, get_db, lib_prefs
from server.libraries import visible_libraries

bp = Blueprint("search", __name__)


def _like(q):
    esc = fold(q).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{esc}%"


@bp.route("/search")
@login_required
def search():
    """Busca por título em filmes, séries e episódios das bibliotecas liberadas ao usuário."""
    q = (request.args.get("q") or "").strip()
    movies, shows, videos, eps, cols = [], [], [], [], []
    allowed = [l["id"] for l in visible_libraries(session["user_id"]) if lib_prefs(l)["visibility"] != "hide_all"]  # 28.6
    if q and allowed:
        marks = ",".join("?" * len(allowed))
        like = _like(q)
        with get_db() as conn:
            rows = conn.execute(
                "SELECT m.id, dtitle(m.library_id, m.title, m.original_title) AS title, m.year, l.type FROM media m JOIN libraries l ON l.id = m.library_id "
                f"WHERE m.library_id IN ({marks}) AND (fold(m.title) LIKE ? ESCAPE '\\' OR fold(m.original_title) LIKE ? ESCAPE '\\') ORDER BY fold(m.title), m.id",
                allowed + [like, like],
            ).fetchall()
            eps = conn.execute(
                "SELECT e.id, e.season, e.episode, e.title, m.id AS mid, m.title AS show "
                "FROM episodes e JOIN media m ON m.id = e.media_id "
                f"WHERE m.library_id IN ({marks}) AND fold(e.title) LIKE ? ESCAPE '\\' "
                "ORDER BY fold(m.title), m.id, e.season, e.episode LIMIT 60",
                allowed + [like],
            ).fetchall()
            cols = conn.execute(
                "SELECT c.id, c.title, c.smart, c.library_id, c.rules, c.limit_n, COUNT(ci.media_id) AS n FROM collections c "
                "LEFT JOIN collection_items ci ON ci.collection_id = c.id "
                f"WHERE c.library_id IN ({marks}) AND fold(c.title) LIKE ? ESCAPE '\\' "
                "GROUP BY c.id ORDER BY fold(c.title), c.id LIMIT 30",
                allowed + [like],
            ).fetchall()
        if any(c["smart"] for c in cols):  # 31.3: contagem das coleções inteligentes vem das regras
            from server.collections import smart_ids
            with get_db() as conn:
                cols = [{**dict(c), "n": len(smart_ids(conn, c))} if c["smart"] else c for c in cols]
        with get_db() as conn:  # 35.20: barra de progresso nos cards
            pm = pct_map(conn, session["profile_id"], [r["id"] for r in rows])
        rows = [{**dict(r), "pct": pm.get(r["id"])} for r in rows]
        movies = [r for r in rows if r["type"] == "movie"]
        shows = [r for r in rows if r["type"] == "show"]
        videos = [r for r in rows if r["type"] == "video"]  # 34.8
    if request.args.get("json") == "1":
        items = [{"title": r["title"], "year": r["year"], "img": f"/poster/{r['id']}",
                  "url": f"/{r['type']}/{r['id']}", "kind": r["type"]} for r in (movies + shows)[:8]]
        items += [{"title": r["title"], "year": None, "img": f"/thumb/{r['id']}", "url": f"/watch/movie/{r['id']}", "kind": "video"}
                  for r in videos[:max(0, 8 - len(items))]]
        items = [{"title": c["title"], "year": None, "img": f"/collection-poster/{c['id']}",
                  "url": f"/collection/{c['id']}", "kind": "collection"} for c in cols[:3]] + items
        return jsonify(items=items[:10])
    return render_template("search.html", q=q, movies=movies, shows=shows, videos=videos, eps=eps, cols=cols)


# ---------- 54.17: busca do celular (resultados ao digitar, até 12 capas) ----------
_M_MAX = 12
_PT_LANGS = {"por", "pt", "pob", "ptb"}
_AGE = {"L": "L", "LIVRE": "L", "ER": "L", "G": "L", "TV-Y": "L", "TV-G": "L", "TV-Y7": "10", "TV-Y7-FV": "10", "PG": "10", "TV-PG": "10",
        "PG-13": "12", "TV-14": "14", "R": "16", "NC-17": "18", "TV-MA": "18"}


def _age(cr):
    """Classificação indicativa em L/10/12/14/16/18 (aceita também as siglas dos EUA); None se não houver."""
    s = (cr or "").strip().upper()
    if not s:
        return None
    if s in _AGE:
        return _AGE[s]
    m = re.search(r"\b(10|12|14|16|18)\b", s)
    return m.group(1) if m else None


def _pt_audio(raw):
    """True se o arquivo (JSON de ffprobe em `info`) tem uma faixa de ÁUDIO em português (legenda não conta)."""
    try:
        info = json.loads(raw) if raw else {}
    except ValueError:
        return False
    for a in (info.get("audio") or []) if isinstance(info, dict) else []:
        lang = re.split(r"[-_.\s]", str(a.get("lang") or "").lower())[0]
        title = fold(a.get("title") or "")
        if lang in _PT_LANGS or re.search(r"portug|dublad|brazil|\bpt[-_ ]?br\b", title):
            return True
    return False


def _rank(fq, names):
    """Menor = mais próximo da busca: 0 exato, 1 começa com, 2 palavra começa com, 3 contém tudo, 4 aproximado."""
    best = (9, 0)
    for t in names:
        if not t:
            continue
        if t == fq:
            r = (0, 0)
        elif t.startswith(fq):
            r = (1, len(t) - len(fq))
        elif (" " + fq) in (" " + re.sub(r"[^\w]+", " ", t)):
            r = (2, len(t) - len(fq))
        elif fq in t or all(w in t for w in fq.split()):
            r = (3, len(t) - len(fq))
        else:
            n = len(fq)
            sc = max(difflib.SequenceMatcher(None, fq, t).ratio(), difflib.SequenceMatcher(None, fq, t[:n + 2]).ratio())
            r = (4, int((1 - sc) * 1000))
        if r < best:
            best = r
    return best


@bp.route("/search/m")
@login_required
def search_mobile():
    """JSON da busca do celular: até 12 itens (filmes, séries e vídeos), o mais próximo/exato primeiro."""
    q = (request.args.get("q") or "").strip()
    fq = fold(q)
    items = []
    allowed = [l["id"] for l in visible_libraries(session["user_id"]) if lib_prefs(l)["visibility"] != "hide_all"]
    if fq and allowed:
        marks = ",".join("?" * len(allowed))
        toks = fq.split()
        tcond = lambda col: "(" + " AND ".join(f"fold({col}) LIKE ? ESCAPE '\\'" for _ in toks) + ")"
        targs = [_like(t) for t in toks]
        with get_db() as conn:
            rows = conn.execute(
                "SELECT m.id, dtitle(m.library_id, m.title, m.original_title) AS title, m.title AS t0, m.original_title AS t1, m.year, m.info, "
                "m.content_rating, m.library_id, l.name AS lib, l.type FROM media m JOIN libraries l ON l.id = m.library_id "
                f"WHERE m.library_id IN ({marks}) AND ({tcond('m.title')} OR {tcond('m.original_title')})",
                allowed + targs + targs,
            ).fetchall()
            rows = [dict(r) for r in rows]
            if len(rows) < _M_MAX and len(fq) >= 3:  # sem acerto exato o bastante: aproxima por semelhança (erro de digitação)
                have = {r["id"] for r in rows}
                for r in conn.execute(
                    "SELECT m.id, dtitle(m.library_id, m.title, m.original_title) AS title, m.title AS t0, m.original_title AS t1, m.year, m.info, "
                    "m.content_rating, m.library_id, l.name AS lib, l.type FROM media m JOIN libraries l ON l.id = m.library_id "
                    f"WHERE m.library_id IN ({marks})", allowed):
                    if r["id"] in have:
                        continue
                    t = fold(r["t0"])
                    n = len(fq)
                    sm = difflib.SequenceMatcher(None, fq, t)
                    if sm.real_quick_ratio() < 0.6 or sm.quick_ratio() < 0.6:
                        continue
                    if max(sm.ratio(), difflib.SequenceMatcher(None, fq, t[:n + 2]).ratio()) >= 0.72:
                        rows.append(dict(r))
            for r in rows:
                r["rk"] = _rank(fq, [fold(r["t0"]), fold(r["t1"]), fold(r["title"])])
            rows.sort(key=lambda r: (r["rk"], fold(r["title"]), r["id"]))
            rows = rows[:_M_MAX]
            for r in rows:
                kind = r["type"]
                last, dub = None, False
                if kind == "show":
                    e = conn.execute("SELECT season, episode FROM episodes WHERE media_id = ? ORDER BY (season = 0), season DESC, episode DESC LIMIT 1", (r["id"],)).fetchone()
                    if e:
                        last = f"T{e['season']:02d}E{e['episode']:02d}"
                    for e in conn.execute(
                            "SELECT info FROM episodes WHERE media_id = ? AND (info LIKE '%\"por\"%' OR info LIKE '%\"pt%' OR info LIKE '%\"pob\"%' "
                            "OR info LIKE '%ortugu%' OR info LIKE '%ublad%' OR info LIKE '%razil%') LIMIT 25", (r["id"],)):
                        if _pt_audio(e["info"]):
                            dub = True
                            break
                else:
                    dub = _pt_audio(r["info"])
                path = {"movie": "/movie/", "show": "/show/", "video": "/watch/movie/"}[kind]
                items.append({"id": r["id"], "href": path + str(r["id"]), "img": ("/thumb/" if kind == "video" else "/poster/") + str(r["id"]),
                              "title": r["title"], "year": r["year"], "lib": r["lib"], "lib_id": r["library_id"], "dub": dub,
                              "age": _age(r["content_rating"]), "last": last})
    return jsonify(items=items, q=q)
