"""40.5: rotas JSON da TV (/api/tv/...). Só leitura e ações simples; toda a lógica vem dos módulos existentes (home_rows, libraries, browse,
collections, playlists, mylist, progress). Autenticação por Bearer + `X-Profile` (40.4); só o que o usuário pode acessar (`can_access`, `visibility`)."""
import json

from flask import Blueprint, abort, jsonify, request, session

from server.auth import login_required
from server.db import display_title, fold, get_db, hdr_label, lib_prefs
from server.libraries import _args, _filtered, _get_lib, _items, can_access, pinned_libraries, visible_libraries
from server.i18n import E, jerr

bp = Blueprint("tv_api", __name__, url_prefix="/api/tv")

PAGE, PAGE_MAX = 60, 200


@bp.errorhandler(404)
def _e404(_e):
    return jerr("err.nao_encontrado", 404)


@bp.errorhandler(400)
def _e400(_e):
    return jerr("err.pedido_invalido", 400)


@bp.errorhandler(403)
def _e403(_e):
    return jerr("err.acesso_negado", 403)


def _dur(raw):
    try:
        return (json.loads(raw) if raw else {}).get("duration") or 0
    except ValueError:
        return 0


def card(i):
    """Item de fileira/lista (formato do motor do Início ou de `_items`) -> card único da TV: type, id, title, sub, image, pct, watched, play."""
    t = i.get("type")
    out = {"uid": i.get("uid"), "type": t or "movie", "id": i["id"], "title": i.get("title") or i.get("show") or "", "sub": None,
           "year": i.get("year"), "pct": int(i.get("pct") or 0), "watched": bool(i.get("watched")), "wide": False, "play": None}
    if i.get("kind") == "episode" and not t:  # Continue assistindo (16:9): `id` é o episódio
        out.update(type="episode", title=i.get("show") or "", sub=i.get("title") or "", season=i.get("season"), episode=i.get("episode"),
                   image=i.get("still") or f"/still/{i['id']}", wide=True, play=f"/stream/episode/{i['id']}/play", media_id=i.get("media_id"))
    elif t == "collection":
        out.update(image=f"/collection-poster/{i['id']}", n=i.get("n", 0))
    elif t == "playlist":
        out.update(image=f"/playlist-image/{i['id']}/poster", n=i.get("n", 0), dur=i.get("dur") or "", library=i.get("lib"))
    elif t == "video":
        out.update(image=i.get("still") or f"/thumb/{i['id']}", wide=True, play=f"/stream/movie/{i['id']}/play", year=None)
    else:
        out.update(image=f"/poster/{i['id']}", play=f"/stream/movie/{i['id']}/play" if t == "movie" else None)
        if i.get("season") is not None and i.get("episode_id"):  # série em andamento: o ▶ abre o episódio
            out.update(sub=i.get("ep_title") or "", season=i["season"], episode=i.get("episode"), episode_id=i["episode_id"],
                       play=f"/stream/episode/{i['episode_id']}/play")
        elif i.get("new"):
            out["sub"] = f"{i['new']} novo{'' if i['new'] == 1 else 's'} ep."
        elif t != "movie" and i.get("year"):
            out["sub"] = str(i["year"])
        if t == "movie" and i.get("year"):
            out["sub"] = str(i["year"])
    return out


def _media(mid, kind):
    """Linha de `media` acessível ao usuário e do tipo de biblioteca `kind` (movie/show/video); 404 caso contrário."""
    with get_db() as conn:
        m = conn.execute("SELECT m.*, l.type AS ltype FROM media m JOIN libraries l ON l.id = m.library_id WHERE m.id = ?", (mid,)).fetchone()
    if not m or m["ltype"] != kind or not can_access(session["user_id"], m["library_id"]):
        abort(404)
    return m


def _images(m):
    return {"poster": f"/poster/{m['id']}", "backdrop": f"/backdrop/{m['id']}" if m["backdrop"] else None,
            "logo": f"/logo/{m['id']}" if m["logo"] else None}


_LANGS = {"por": "lang.pt", "pt": "lang.pt", "eng": "lang.en", "en": "lang.en", "spa": "lang.es", "es": "lang.es", "jpn": "lang.ja",
          "fre": "lang.fr", "fra": "lang.fr", "ger": "lang.de", "deu": "lang.de", "ita": "lang.it"}  # chaves do catálogo
_CODECS = {"h264": "H.264", "hevc": "HEVC", "av1": "AV1", "mpeg4": "MPEG-4", "vp9": "VP9"}
_CHANNELS = {1: "Mono", 2: "Stereo", 6: "5.1", 8: "7.1"}


def _tech(raw):
    """43.4: selos técnicos do arquivo (ex.: `720p (H.264)`, `Português (AC3 Stereo)`)."""
    try:
        info = json.loads(raw) if raw else {}
    except ValueError:
        return []
    out = []
    v = info.get("video") or {}
    if v.get("height"):
        out.append(f"{v['height']}p ({_CODECS.get(v.get('codec'), (v.get('codec') or '').upper())})")
    if hdr_label(info):
        out.append(hdr_label(info))  # 50.1: só quando existir
    a = (info.get("audio") or [None])[0]
    if a:
        name = a.get("title") or (E(_LANGS[(a.get("lang") or "").lower()]) if (a.get("lang") or "").lower() in _LANGS else E("det.unknown"))
        out.append(f"{name} ({' '.join(x for x in ((a.get('codec') or '').upper(), _CHANNELS.get(a.get('channels'), '')) if x)})")
    return out


def _reviews(x):
    """43.6: análises do TMDB já guardadas em `reviews` (vazio se o perfil escolheu \"Ninguém\")."""
    return [{"author": r["author"] or E("det.anonymous"), "rating": r["rating"], "created": r["created"] or "", "text": (r["text"] or "")[:1200]} for r in x["reviews"][:20]]


def _directors(x):
    return [c["name"] for c in x["cast"] if c["role"] == "director"][:2]


def _genres(m):
    return [g.strip() for g in (m["genres"] or "").split(",") if g.strip()]


# ---- perfis e navegação ----
@bp.route("/profiles")
@login_required
def profiles():
    """Perfis do usuário do token (a TV escolhe um e passa a enviar `X-Profile`)."""
    with get_db() as conn:
        rows = conn.execute("SELECT id, name, avatar FROM profiles WHERE user_id = ? ORDER BY fold(name), id", (session["user_id"],)).fetchall()
        photos = {r["id"]: r["photo"] for r in conn.execute("SELECT id, photo FROM profiles WHERE user_id = ?", (session["user_id"],))}
    from server.account import profile_photo_url
    return jsonify(profiles=[{"id": r["id"], "name": r["name"], "avatar": r["avatar"], "photo": profile_photo_url(r["id"], photos.get(r["id"]))} for r in rows])


@bp.route("/libraries")
@login_required
def libraries():
    """Menu lateral: bibliotecas liberadas e fixadas do usuário."""
    return jsonify(libraries=[{"id": l["id"], "name": l["name"], "type": l["type"]} for l in pinned_libraries(session["user_id"])])


@bp.route("/home")
@login_required
def home():
    """Início: fileiras do motor (32.3) com os itens já no formato de card."""
    from server.home_rows import build_rows_cached
    rows = build_rows_cached(session["user_id"], session["profile_id"], fresh=True)
    return jsonify(rows=[{"key": r["key"], "title": r["title"], "type": r["type"],
                          "items": [_continue_card(i) if r["key"] == "continue" else card(i) for i in r["items"]]} for r in rows])


def _continue_card(i):
    """57.11: Continuar assistindo no Início da TV em 16:9 (nunca capa): episódio = frame do episódio; filme = fundo (backdrop); vídeo já vem com a miniatura."""
    c = card(i)
    if c["type"] == "show" and i.get("episode_id"):
        c.update(wide=True, image=f"/still/{i['episode_id']}")
    elif c["type"] == "movie":
        c.update(wide=True, image=i.get("bd") or f"/backdrop/{i['id']}")
    return c


@bp.route("/continue")
@login_required
def continue_list():
    from server.progress import continue_watching
    out = []
    for i in continue_watching(session["user_id"], session["profile_id"]):
        pct = min(100, int(i["position"] / i["duration"] * 100)) if i.get("duration") else 0
        if i["kind"] == "episode":
            out.append({"type": "episode", "id": i["id"], "media_id": i["media_id"], "title": i["show"], "sub": i["title"] or "", "season": i["season"],
                        "episode": i["episode"], "pct": pct, "watched": False, "wide": True, "image": f"/still/{i['id']}",
                        "play": f"/stream/episode/{i['id']}/play", "position": i["position"]})
        else:
            out.append({"type": "movie", "id": i["id"], "title": i["title"], "sub": str(i["year"] or ""), "year": i["year"], "pct": pct, "watched": False,
                        "wide": True, "image": f"/backdrop/{i['id']}", "play": f"/stream/movie/{i['id']}/play", "position": i["position"]})
    return jsonify(items=out)


# ---- biblioteca ----
@bp.route("/library/<int:lid>")
@login_required
def library(lid):
    """Grade paginada (`offset`, `limit`) com ordem/filtro da URL ou, sem eles, os últimos escolhidos pelo perfil (38.4)."""
    lib = _get_lib(lid)
    sort, d, flt, genre = _args(lid)
    allitems = _items(lid, lib["type"], sort, d, flt, "")
    genres = sorted({g for i in allitems for g in i["genres"]}, key=fold)
    items = _filtered(allitems, flt, genre)
    try:
        offset = max(0, int(request.args.get("offset", 0)))
        limit = min(PAGE_MAX, max(1, int(request.args.get("limit", PAGE))))
    except ValueError:
        abort(400)
    t = lib["type"]
    page = [card({"id": i["id"], "type": t, "title": i["title"], "year": i["year"], "pct": i["pct"], "watched": i["watched"]}) for i in items[offset:offset + limit]]
    return jsonify(library={"id": lid, "name": lib["name"], "type": t}, view={"sort": sort, "dir": d, "filter": flt, "genre": genre},
                   genres=genres, total=len(items), offset=offset, items=page)


@bp.route("/library/<int:lid>/collections")
@login_required
def library_collections_(lid):
    from server.collections import library_collections
    _get_lib(lid)
    with get_db() as conn:
        cols = library_collections(conn, lid)
    show = request.args.get("all") == "1" or any(not c["smart"] or c["n"] for c in cols)
    return jsonify(items=[card({"id": c["id"], "type": "collection", "title": c["title"], "n": c["n"]}) for c in cols] if show else [])


# ---- detalhes ----
@bp.route("/movie/<int:mid>")
@login_required
def movie(mid):
    from server.browse import detail_extras
    from server.mylist import get_stars, in_list
    from server.progress import RESUME_MIN
    m = _media(mid, "movie")
    with get_db() as conn:
        p = conn.execute("SELECT position, watched FROM progress WHERE profile_id = ? AND item_type = 'movie' AND item_id = ?",
                         (session["profile_id"], mid)).fetchone()
    dur, pos = _dur(m["info"]), (p["position"] if p and p["position"] > RESUME_MIN else 0)
    x = detail_extras(m, "movie")
    return jsonify(type="movie", id=mid, title=display_title(m["library_id"], m["title"], m["original_title"]), year=m["year"],
                   tagline=m["tagline"] or "", overview=m["overview"] or "", genres=_genres(m), content_rating=m["content_rating"] or "",
                   rating=m["rating"], imdb=m["imdb_rating"], rt=m["rt_rating"], directors=_directors(x), reviews=_reviews(x), tech=_tech(m["info"]), duration=dur, position=pos, watched=bool(p and p["watched"]), in_list=in_list(mid), stars=get_stars("movie", mid),
                   library=m["library_id"], images=_images(m), play=f"/stream/movie/{mid}/play",
                   cast=[{"id": c["id"], "name": c["name"], "label": c["label"], "role": c["role"], "image": f"/person/{c['id']}"} for c in x["cast"][:12]],
                   related=[card({"id": r["id"], "type": "movie", "title": r["title"], "year": r["year"], "watched": bool(r["seen"]), "pct": r["pct"]}) for r in x["related"]])


@bp.route("/show/<int:mid>")
@login_required
def show(mid):
    from server.browse import detail_extras
    from server.mylist import get_stars, in_list
    m = _media(mid, "show")
    with get_db() as conn:
        eps = conn.execute(
            "SELECT e.id, e.season, e.episode, COALESCE(p.watched, 0) AS watched FROM episodes e "
            "LEFT JOIN progress p ON p.item_type = 'episode' AND p.item_id = e.id AND p.profile_id = ? WHERE e.media_id = ? ORDER BY e.season, e.episode",
            (session["profile_id"], mid)).fetchall()
    ns = sorted({e["season"] for e in eps}, key=lambda n: (n == 0, n))  # especiais por último
    seasons = []
    for n in ns:
        es = [e for e in eps if e["season"] == n]
        seasons.append({"n": n, "count": len(es), "watched": sum(1 for e in es if e["watched"]), "image": f"/season-poster/{mid}/{n}"})
    regular = [e for e in eps if e["season"] != 0] or list(eps)  # T0 não define "Reproduzir/Próximo"
    nxt = next((e for e in regular if not e["watched"]), None)
    play = nxt or (regular[0] if regular else None)
    x = detail_extras(m, "show")
    return jsonify(type="show", id=mid, title=display_title(m["library_id"], m["title"], m["original_title"]), year=m["year"],
                   tagline=m["tagline"] or "", overview=m["overview"] or "", genres=_genres(m), content_rating=m["content_rating"] or "",
                   rating=m["rating"], imdb=m["imdb_rating"], rt=m["rt_rating"], directors=_directors(x), reviews=_reviews(x), in_list=in_list(mid), stars=get_stars("show", mid), library=m["library_id"], images=_images(m),
                   seasons=seasons, total=len(eps), watched_count=sum(1 for e in eps if e["watched"]),
                   play={"episode_id": play["id"], "season": play["season"], "episode": play["episode"],
                         "next_up": bool(nxt and any(e["watched"] for e in regular)), "url": f"/stream/episode/{play['id']}/play"} if play else None,
                   cast=[{"id": c["id"], "name": c["name"], "label": c["label"], "role": c["role"], "image": f"/person/{c['id']}"} for c in x["cast"][:12]],
                   related=[card({"id": r["id"], "type": "show", "title": r["title"], "year": r["year"], "watched": False, "pct": r["pct"]}) for r in x["related"]])


@bp.route("/show/<int:mid>/season/<int:n>")
@login_required
def season(mid, n):
    from server.browse import _season_data
    m, _lib, seasons, eps = _season_data(mid, n)
    return jsonify(show={"id": mid, "title": display_title(m["library_id"], m["title"], m["original_title"])}, season=n, seasons=seasons,
                   episodes=[{"id": e["id"], "season": n, "episode": e["episode"], "title": e["title"] or "", "position": e["position"],
                              "watched": e["watched"], "pct": int(e["pct"] or 0), "image": f"/still/{e['id']}", "play": f"/stream/episode/{e['id']}/play"}
                             for e in eps])


@bp.route("/episode/<int:eid>")
@login_required
def episode(eid):
    from server.mylist import get_stars
    from server.progress import RESUME_MIN
    with get_db() as conn:
        e = conn.execute("SELECT * FROM episodes WHERE id = ?", (eid,)).fetchone()
        if not e:
            abort(404)
        m = _media(e["media_id"], "show")
        p = conn.execute("SELECT position, watched FROM progress WHERE profile_id = ? AND item_type = 'episode' AND item_id = ?",
                         (session["profile_id"], eid)).fetchone()
        sibs = [r["id"] for r in conn.execute("SELECT id FROM episodes WHERE media_id = ? ORDER BY season = 0, season, episode", (m["id"],))]
    i = sibs.index(eid)
    dur, pos = _dur(e["info"]), (p["position"] if p and p["position"] > RESUME_MIN else 0)
    with get_db() as conn:  # 43.5: direção do episódio (créditos com episode_id)
        dirs = [r["name"] for r in conn.execute("SELECT p.name FROM credits c JOIN people p ON p.id = c.person_id WHERE c.episode_id = ? AND c.role = 'director' ORDER BY c.ord LIMIT 2", (eid,))]
    return jsonify(type="episode", imdb=e["imdb_rating"], tech=_tech(e["info"]), directors=dirs, id=eid, media_id=m["id"], show=display_title(m["library_id"], m["title"], m["original_title"]),
                   season=e["season"], episode=e["episode"], title=e["title"] or "", overview=e["overview"] or "", air_date=e["air_date"] or "",
                   duration=dur, position=pos, watched=bool(p and p["watched"]), stars=get_stars("episode", eid), image=f"/still/{eid}",
                   prev_id=sibs[i - 1] if i > 0 else None, next_id=sibs[i + 1] if i + 1 < len(sibs) else None, play=f"/stream/episode/{eid}/play")


def _dur_txt(sec):
    """55.1: \"47 minutos\", \"1 hora\", \"1 hora 2 minutos\" (vazio sem duração)."""
    mins = round((sec or 0) / 60)
    if mins <= 0:
        return ""
    h, m = divmod(mins, 60)
    parts = ([f"{h} hora" + ("s" if h > 1 else "")] if h else []) + ([f"{m} minuto" + ("s" if m > 1 else "")] if m else [])
    return " ".join(parts)


@bp.route("/next/<kind>/<int:item_id>")
@login_required
def next_items(kind, item_id):
    """55.1: cabeçalho do player do celular e episódios seguintes. Episódio: `current` + `items` (o atual primeiro, depois os seguintes
    da série, especiais por último, no máximo 200; arquivo repetido S01E01E02 conta uma vez) + `prev_id`/`next_id`; filme/vídeo: só `current`, `items` vazio."""
    if kind not in ("episode", "movie", "video"):
        abort(404)
    if kind != "episode":
        m = _media(item_id, kind)
        parts = ([str(m["year"])] if m["year"] and kind == "movie" else []) + ([_dur_txt(_dur(m["info"]))] if _dur(m["info"]) else [])
        return jsonify(kind=kind, current={"id": item_id, "title": display_title(m["library_id"], m["title"], m["original_title"]), "line": " • ".join(parts)},
                       items=[], prev_id=None, next_id=None)
    with get_db() as conn:
        e = conn.execute("SELECT media_id FROM episodes WHERE id = ?", (item_id,)).fetchone()
        if not e:
            abort(404)
        m = _media(e["media_id"], "show")
        rows = conn.execute("SELECT id, season, episode, title, path, info FROM episodes WHERE media_id = ? ORDER BY season = 0, season, episode", (m["id"],)).fetchall()
    show = display_title(m["library_id"], m["title"], m["original_title"])
    uniq, seen = [], set()
    for r in rows:
        if r["path"] in seen and r["id"] != item_id:
            continue
        seen.add(r["path"])
        uniq.append(r)
    ids = [r["id"] for r in uniq]
    i = ids.index(item_id)

    def row(r):
        line = " • ".join(x for x in (f"S{r['season']}", f"E{r['episode']}", show, _dur_txt(_dur(r["info"]))) if x)
        return {"id": r["id"], "season": r["season"], "episode": r["episode"], "title": r["title"] or show, "line": line, "image": f"/still/{r['id']}"}

    items = [row(r) for r in uniq[i:i + 200]]
    return jsonify(kind=kind, current=items[0], items=items, show=show, prev_id=ids[i - 1] if i > 0 else None, next_id=ids[i + 1] if i + 1 < len(ids) else None)


@bp.route("/collection/<int:cid>")
@login_required
def collection(cid):
    from server.collections import _first, collection_media, get_collection
    with get_db() as conn:
        c = get_collection(conn, cid)
        lib = conn.execute("SELECT id, name, type FROM libraries WHERE id = ?", (c["library_id"],)).fetchone()
        rows = collection_media(conn, cid)
        fl = _first(conn, cid, "logo")
    logo = f"/collection-logo/{cid}" if c["logo"] else (f"/logo/{fl['id']}" if fl else None)  # logo da coleção ou do 1º item que tenha
    state = {i["id"]: i for i in _items(lib["id"], lib["type"], "title", "asc", "all", "")}
    items = [state[r["id"]] for r in rows if r["id"] in state]
    nxt = next((i for i in items if not i["watched"]), items[0] if items else None)
    return jsonify(type="collection", id=cid, title=c["title"], overview=c["summary"] or "", library=lib["id"], image=f"/collection-poster/{cid}",
                   backdrop=f"/collection-backdrop/{cid}", logo=logo, next_id=nxt["id"] if nxt else None,
                   items=[card({"id": i["id"], "type": lib["type"], "title": i["title"], "year": i["year"], "pct": i["pct"], "watched": i["watched"]}) for i in items])


@bp.route("/playlists")
@login_required
def playlists():
    from server.playlists import playlist_ids
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM playlists WHERE user_id = ? ORDER BY fold(title), id", (session["user_id"],)).fetchall()
        rows = [p for p in rows if can_access(session["user_id"], p["library_id"])]
        out = [{"id": p["id"], "title": p["title"], "library": p["library_id"], "n": len(playlist_ids(conn, p)), "image": f"/playlist-image/{p['id']}/poster"} for p in rows]
    return jsonify(playlists=out)


@bp.route("/playlist/<int:pid>")
@login_required
def playlist(pid):
    from server.playlists import get_playlist, playlist_ids
    with get_db() as conn:
        p = get_playlist(conn, pid)
        lib = conn.execute("SELECT id, name, type FROM libraries WHERE id = ?", (p["library_id"],)).fetchone()
        ids = playlist_ids(conn, p)
    state = {i["id"]: i for i in _items(lib["id"], lib["type"], "title", "asc", "all", "")}
    items = [state[m] for m in ids if m in state]
    return jsonify(type="playlist", id=pid, title=p["title"], library=lib["id"], image=f"/playlist-image/{pid}/poster",
                   items=[card({"id": i["id"], "type": lib["type"], "title": i["title"], "year": i["year"], "pct": i["pct"], "watched": i["watched"]}) for i in items])


# ---- Minha Lista, busca, progresso ----
WATCHNEXT_MAX = 10


def _ms(ts):
    """`updated_at` do SQLite (UTC, 'AAAA-MM-DD HH:MM:SS') -> milissegundos desde 1970."""
    import calendar
    import time
    try:
        return calendar.timegm(time.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")) * 1000
    except (TypeError, ValueError):
        return 0


@bp.route("/watchnext")
@login_required
def watchnext():
    """52.14: itens da linha \"Reproduzir a seguir\" do launcher da TV: em andamento (`continue`) e próximo episódio das séries assistidas (`next`).
    Reaproveita `continue_watching` e a fileira Em Cartaz do Início; respeita acesso e visibilidade; assistido não entra; no máximo 10, mais recentes primeiro."""
    from server.home_rows import Ctx
    from server.home_usage import on_deck
    from server.progress import continue_watching
    uid, pid = session["user_id"], session["profile_id"]
    types = {l["id"]: l["type"] for l in visible_libraries(uid)}
    out = []
    for i in continue_watching(uid, pid, limit=WATCHNEXT_MAX, home=True):
        dur = int((i.get("duration") or 0) * 1000)
        pos = int(i["position"] * 1000)
        if i["kind"] == "episode":
            out.append({"key": f"episode:{i['id']}", "type": "episode", "id": i["id"], "title": i["title"] or E("det.episode_n", n=i["episode"]), "series": i["show"],
                        "season": i["season"], "episode": i["episode"], "duration_ms": dur, "position_ms": pos, "image": f"/still/{i['id']}",
                        "last_played": _ms(i.get("updated_at")), "kind": "continue"})
        else:
            out.append({"key": f"movie:{i['id']}", "type": "movie", "id": i["id"], "title": i["title"], "series": None, "season": None, "episode": None,
                        "duration_ms": dur, "position_ms": pos, "image": f"/thumb/{i['id']}" if types.get(i.get("lib")) == "video" else f"/poster/{i['id']}",
                        "last_played": _ms(i.get("updated_at")), "kind": "continue"})
    have = {o["key"] for o in out}
    with get_db() as conn:
        for d in on_deck(Ctx(uid, pid)):
            key = f"episode:{d['episode_id']}"
            if key in have:
                continue
            e = conn.execute("SELECT info FROM episodes WHERE id = ?", (d["episode_id"],)).fetchone()
            last = conn.execute(
                "SELECT MAX(p.updated_at) FROM progress p JOIN episodes e ON e.id = p.item_id WHERE p.profile_id = ? AND p.item_type = 'episode' AND e.media_id = ?",
                (pid, d["id"])).fetchone()[0]
            out.append({"key": key, "type": "episode", "id": d["episode_id"], "title": d["ep_title"] or E("det.episode_n", n=d["episode"]), "series": d["title"],
                        "season": d["season"], "episode": d["episode"], "duration_ms": int(_dur(e["info"]) * 1000) if e else 0, "position_ms": 0,
                        "image": f"/still/{d['episode_id']}", "last_played": _ms(last), "kind": "next"})
    out.sort(key=lambda o: o["last_played"], reverse=True)
    return jsonify(items=out[:WATCHNEXT_MAX])


@bp.route("/mylist")
@login_required
def mylist():
    from server.mylist import my_list_items
    return jsonify(items=[card(i) for i in my_list_items(session["profile_id"], session["user_id"])])


@bp.route("/mylist/<int:mid>", methods=["POST", "DELETE"])
@login_required
def mylist_toggle(mid):
    """Liga (POST) ou desliga (DELETE) o item na Minha Lista do perfil."""
    from server.mylist import toggle
    return toggle(mid)


@bp.route("/watched/<kind>/<int:item_id>", methods=["POST"])
@login_required
def watched(kind, item_id):
    """Marca como assistido (padrão) ou não assistido: corpo `{"watched": false}`."""
    from server.progress import set_watched
    return set_watched(kind, item_id)


@bp.route("/markers/<int:eid>")
@login_required
def markers(eid):
    """57.22: marcadores de abertura/créditos do episódio + preferências do perfil (Pular abertura, Próximo episódio automático) para o player nativo."""
    from server.account import user_prefs
    from server.markers import episode_markers
    out = episode_markers(eid).get_json()
    up = user_prefs()
    out.update(skip_intro=up["skip_intro"], auto_next=up["auto_next"])
    return jsonify(out)


@bp.route("/sub-style")
@login_required
def sub_style():
    """57.29: estilo da legenda do perfil (tamanho, cor, fundo, altura) para o player nativo da TV/celular."""
    from server.account import user_prefs
    up = user_prefs()
    return jsonify({k: up[k] for k in ("sub_size", "sub_color", "sub_bg", "sub_pos")})


@bp.route("/next/<int:eid>")
@login_required
def next_ep(eid):
    from server.progress import next_ep as _next
    return _next(eid)


@bp.route("/search")
@login_required
def search():
    """Busca por título (filmes, séries, vídeos, coleções) nas bibliotecas liberadas e não ocultas da busca (28.6)."""
    from server.search import _like
    q = (request.args.get("q") or "").strip()[:100]
    allowed = [l["id"] for l in visible_libraries(session["user_id"]) if lib_prefs(l)["visibility"] != "hide_all"]
    out = {"movies": [], "shows": [], "videos": [], "collections": []}
    if q and allowed:
        marks, like = ",".join("?" * len(allowed)), _like(q)
        with get_db() as conn:
            rows = conn.execute(
                "SELECT m.id, dtitle(m.library_id, m.title, m.original_title) AS title, m.year, l.type FROM media m JOIN libraries l ON l.id = m.library_id "
                f"WHERE m.library_id IN ({marks}) AND (fold(m.title) LIKE ? ESCAPE '\\' OR fold(m.original_title) LIKE ? ESCAPE '\\') ORDER BY fold(m.title), m.id LIMIT 60",
                allowed + [like, like]).fetchall()
            cols = conn.execute(
                "SELECT c.id, c.title FROM collections c "
                f"WHERE c.library_id IN ({marks}) AND fold(c.title) LIKE ? ESCAPE '\\' ORDER BY fold(c.title), c.id LIMIT 20", allowed + [like]).fetchall()
        for r in rows:
            out[{"movie": "movies", "show": "shows", "video": "videos"}[r["type"]]].append(card({"id": r["id"], "type": r["type"], "title": r["title"], "year": r["year"]}))
        out["collections"] = [card({"id": c["id"], "type": "collection", "title": c["title"]}) for c in cols]
    return jsonify(q=q, **out)
