import json
import re

from flask import Blueprint, abort, redirect, render_template, request, session

from server import i18n
from server.account import SETTINGS, user_prefs
from server.auth import login_required
from server.db import display_title, get_db, hdr_label, lib_prefs
from server.libraries import can_access, visible_libraries
from server.mylist import get_stars, in_list
from server.progress import RESUME_MIN
from server.pcts import pct_map
from server.stream import get_item
from server.subtitles import embedded_subs, external_subs

bp = Blueprint("browse", __name__)


def _fwd():
    """Repassa ?audio=&sub= (preferências escolhidas na página de detalhe) para o /watch."""
    from urllib.parse import urlencode
    q = {k: request.args[k] for k in ("audio", "sub") if request.args.get(k)}
    return "?" + urlencode(q) if q else ""


def _prefs(mid, n=None):
    """Preferências de áudio/legenda (Avançado, 23.22): da série/filme e, se houver temporada, a dela por cima."""
    out = {}
    with get_db() as conn:
        rows = [conn.execute("SELECT prefs FROM media WHERE id = ?", (mid,)).fetchone()]
        if n is not None:
            rows.append(conn.execute("SELECT prefs FROM seasons WHERE media_id = ? AND season = ?", (mid, n)).fetchone())
    for r in rows:
        try:
            out.update(json.loads(r["prefs"]) if r and r["prefs"] else {})
        except ValueError:
            pass
    return out


def rating_info(m, lib):
    """Nota exibida no detalhe conforme a Fonte de Avaliações da biblioteca (28.5); sem o dado, cai na nota TMDB."""
    src = lib_prefs(lib)["rating_source"]
    if src == "imdb" and m["imdb_rating"]:
        return {"cls": "mv-ext", "title": i18n.tr("det.rating_imdb"), "text": f"IMDb {m['imdb_rating']:.1f}"}
    if src == "rt" and m["rt_rating"] is not None:
        return {"cls": "mv-ext", "title": "Rotten Tomatoes", "text": f"RT {m['rt_rating']}%"}
    if m["rating"]:
        return {"cls": "", "title": i18n.tr("det.rating_tmdb"), "text": f"TMDB {m['rating']:.1f}"}
    return None


def fmt_duration(seconds):
    m = int((seconds or 0) // 60)
    if m <= 0:
        return ""
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


def fmt_hm(seconds):
    """Duração curta estilo Plex: 2h 31min / 45min (pelo idioma ativo)."""
    return i18n.fmt_hm(seconds)


def fmt_resume(seconds):
    """Ponto de retomada: segundos abaixo de 1 min, senão h/min."""
    s = int(seconds or 0)
    return f"{s} s" if 0 < s < 60 else fmt_duration(s)


def tech_info(info):
    """Resumo técnico do arquivo (resolução, codecs, áudios) a partir do ffprobe."""
    if not info or info.get("error"):
        return None
    v = info.get("video") or {}
    return {
        "resolution": f"{v['height']}p" if v.get("height") else None,
        "video": (v.get("codec") or "").upper() or None,
        "hdr": hdr_label(info),  # 50.1
        "audio": [
            " ".join(x for x in ((a.get("lang") or "").upper(), (a.get("codec") or "").upper(), f"{a['channels']}ch" if a.get("channels") else "") if x)
            for a in info.get("audio") or []
        ],
        "subs": len(info.get("subs") or []),
    }


ROLE_LABEL = {"director": "det.role.director", "writer": "det.role.writer", "producer": "det.role.producer"}  # chaves do catálogo


def _role(r):
    return i18n.tr(ROLE_LABEL[r]) if r in ROLE_LABEL else ""


def detail_extras(m, kind):
    """Elenco & Equipe, Avaliações & Análises e relacionados (23.17) de um filme/série."""
    mid, pid = m["id"], session["profile_id"]
    libs = [l["id"] for l in visible_libraries(session["user_id"]) if l["type"] == kind]
    with get_db() as conn:
        credits = conn.execute(
            "SELECT p.id, p.name, c.role, c.character FROM credits c JOIN people p ON p.id = c.person_id "
            "WHERE c.media_id = ? AND c.episode_id IS NULL "
            "ORDER BY CASE c.role WHEN 'director' THEN 0 WHEN 'cast' THEN 1 WHEN 'writer' THEN 2 ELSE 3 END, c.ord",
            (mid,),
        ).fetchall()
        reviews = conn.execute(
            "SELECT author, rating, created, text FROM reviews WHERE media_id = ? ORDER BY id", (mid,)
        ).fetchall()
        if user_prefs()["reviews"] == "none":
            reviews = []
        related = []
        if libs:
            ph = ",".join("?" * len(libs))
            sel = (
                "SELECT m.id, dtitle(m.library_id, m.title, m.original_title) AS title, m.year, COALESCE(pm.watched, 0) AS seen FROM media m "
                "LEFT JOIN progress pm ON pm.profile_id = ? AND pm.item_type = 'movie' AND pm.item_id = m.id "
            )
            path = "m.path IS NOT NULL" if kind == "movie" else "m.path IS NULL"
            related = conn.execute(
                sel + "JOIN related r ON r.tmdb_id = m.tmdb_id AND r.media_id = ? "
                f"WHERE m.library_id IN ({ph}) AND {path} AND m.id != ? ORDER BY r.ord LIMIT 20",
                (pid, mid, *libs, mid),
            ).fetchall()
            if not related:  # sem recomendações do TMDB na biblioteca: mesmos gêneros
                related = conn.execute(
                    sel + "JOIN tags t ON t.media_id = m.id AND t.kind = 'genre' "
                    "WHERE t.name IN (SELECT name FROM tags WHERE media_id = ? AND kind = 'genre') "
                    f"AND m.library_id IN ({ph}) AND {path} AND m.id != ? "
                    "GROUP BY m.id ORDER BY COUNT(*) DESC, m.id LIMIT 20",
                    (pid, mid, *libs, mid),
                ).fetchall()
    if related:
        with get_db() as conn:
            pm = pct_map(conn, pid, [x["id"] for x in related])
        related = [{**dict(x), "pct": pm.get(x["id"])} for x in related]
    cast, extra = [], {"writer": 0, "producer": 0}
    for c in credits:
        if c["role"] in extra:
            if extra[c["role"]] >= 3:
                continue
            extra[c["role"]] += 1
        elif c["role"] == "cast" and sum(1 for x in cast if x["role"] == "cast") >= 20:
            continue
        cast.append({"id": c["id"], "name": c["name"], "role": c["role"],
                     "label": c["character"] if c["role"] == "cast" else _role(c["role"])})
    return {
        "cast": cast, "reviews": reviews, "related": related,
        "related_title": i18n.tr("det.related_movies" if kind == "movie" else "det.related_shows"),
        "related_kind": kind,
    }


@bp.route("/movie/<int:mid>")
@login_required
def movie(mid):
    with get_db() as conn:
        m = conn.execute(
            "SELECT m.*, l.type FROM media m JOIN libraries l ON l.id = m.library_id WHERE m.id = ?", (mid,)
        ).fetchone()
        if not m or m["type"] != "movie" or not can_access(session["user_id"], m["library_id"]):
            abort(404)
        prog = conn.execute(
            "SELECT position, watched FROM progress WHERE profile_id = ? AND item_type = 'movie' AND item_id = ?",
            (session["profile_id"], mid),
        ).fetchone()
        lib = conn.execute("SELECT id, name, prefs FROM libraries WHERE id = ?", (m["library_id"],)).fetchone()
    info = json.loads(m["info"]) if m["info"] else None
    pos = prog["position"] if prog and prog["position"] > RESUME_MIN else 0
    dur = (info or {}).get("duration") or 0
    watched_ = bool(prog and prog["watched"])
    pct = min(99.0, pos / dur * 100) if pos and dur and not watched_ else 0
    left = fmt_hm(dur - pos) if pct else ""
    return render_template(
        "movie.html", pct=pct, left=left, prefs=_prefs(mid), m=m, lib=lib, rate=rating_info(m, lib), runtime_hm=fmt_hm((info or {}).get("duration")),
        genres=[g.strip() for g in (m["genres"] or "").split(",") if g.strip()],
        runtime=fmt_duration((info or {}).get("duration")), tech=tech_info(info),
        position=pos, watched=bool(prog and prog["watched"]),
        resume=fmt_resume(pos) if pos else "",
        in_list=in_list(mid), stars=get_stars("movie", mid), **detail_extras(m, "movie"),
    )


@bp.route("/show/<int:mid>")
@login_required
def show(mid):
    """Série: sinopse + temporadas (abas) + lista de episódios com progresso do perfil."""
    with get_db() as conn:
        m = conn.execute(
            "SELECT m.*, l.type FROM media m JOIN libraries l ON l.id = m.library_id WHERE m.id = ?", (mid,)
        ).fetchone()
        if not m or m["type"] != "show" or not can_access(session["user_id"], m["library_id"]):
            abort(404)
        rows = conn.execute(
            "SELECT e.id, e.season, e.episode, e.title, e.overview, e.info, "
            "COALESCE(p.position, 0) AS position, COALESCE(p.watched, 0) AS watched "
            "FROM episodes e LEFT JOIN progress p ON p.item_type = 'episode' AND p.item_id = e.id AND p.profile_id = ? "
            "WHERE e.media_id = ? ORDER BY e.season, e.episode",
            (session["profile_id"], mid),
        ).fetchall()
        lib = conn.execute("SELECT id, name, prefs FROM libraries WHERE id = ?", (m["library_id"],)).fetchone()
    eps = []
    for r in rows:
        pos = r["position"] if r["position"] > RESUME_MIN else 0
        try:
            dur = (json.loads(r["info"]) if r["info"] else {}).get("duration") or 0
        except ValueError:
            dur = 0
        eps.append({
            "id": r["id"], "season": r["season"], "episode": r["episode"], "title": r["title"],
            "overview": r["overview"], "runtime": fmt_duration(dur), "position": pos,
            "watched": bool(r["watched"]), "pct": min(100, int(pos / dur * 100)) if dur and pos else 0,
        })
    seasons = sorted({e["season"] for e in eps})
    def _sp(n):
        es = [e for e in eps if e["season"] == n]
        d = sum(1 for e in es if e["watched"])
        return d / len(es) * 100 if es and 0 < d < len(es) else 0
    season_cards = [{"n": n, "count": sum(1 for e in eps if e["season"] == n), "pct": _sp(n)} for n in seasons]
    if len(season_cards) > 1 and season_cards[0]["n"] == 0:  # especiais (T0) vão por último
        season_cards.append(season_cards.pop(0))
    # temporada padrão: a do primeiro episódio ainda não assistido (ou a primeira)
    regular = [e for e in eps if e["season"] != 0] or eps  # especiais (T0) não definem "Reproduzir/Próximo" nem a aba padrão
    first_open = next((e for e in regular if not e["watched"]), None)
    default = first_open["season"] if first_open else (regular[0]["season"] if regular else 0)
    season = request.args.get("season", type=int)
    if season not in seasons:
        season = default
    return render_template(
        "show.html", prefs=_prefs(mid), m=m, lib=lib, rate=rating_info(m, lib), seasons=seasons, season=season, season_cards=season_cards,
        eps=[e for e in eps if e["season"] == season],
        genres=[g.strip() for g in (m["genres"] or "").split(",") if g.strip()],
        show_pct=(lambda d, t: d / t * 100 if t and 0 < d < t else 0)(sum(1 for e in eps if e["watched"]), len(eps)),
        total=len(eps), watched_count=sum(e["watched"] for e in eps), play=first_open or (regular[0] if regular else None),
        next_up=bool(first_open and any(e["watched"] for e in regular)),
        in_list=in_list(mid), stars=get_stars("show", mid), **detail_extras(m, "show"),
    )


# ---------- Página do episódio (36.1) ----------
_L2 = {"por": "pt", "pt": "pt", "pob": "pt", "eng": "en", "en": "en", "spa": "es", "es": "es", "fra": "fr", "fre": "fr", "fr": "fr",
       "deu": "de", "ger": "de", "de": "de", "ita": "it", "it": "it", "jpn": "ja", "ja": "ja", "kor": "ko", "ko": "ko",
       "zho": "zh", "chi": "zh", "zh": "zh", "rus": "ru", "ru": "ru"}
_CHANNELS = {1: "Mono", 2: "det.stereo", 6: "5.1", 8: "7.1"}  # "det.*" = chave do catálogo
_CODECS = {"eac3": "EAC3", "ac3": "AC3", "aac": "AAC", "dts": "DTS", "truehd": "TrueHD", "mp3": "MP3", "opus": "Opus", "flac": "FLAC"}


def _chan(n):
    v = _CHANNELS.get(n)
    return i18n.tr(v) if v and v.startswith("det.") else v


def _l2(v):
    return _L2.get(re.split(r"[-_.\s]", str(v or "").lower())[0], "")


def _fmt_date(d):
    """'2026-06-04' -> data por extenso no idioma ativo; formato desconhecido volta como veio."""
    return i18n.fmt_date(d) or d or ""


def _track_options(path, info, pf):
    """Listas dos seletores Áudio e Legendas da página do episódio: [(valor, rótulo)] e o valor escolhido.
    O valor é o código de idioma que o /watch já entende (?audio=pt&sub=en|off); a escolha padrão segue as preferências do item/conta."""
    up = user_prefs()
    auto = up["auto"]
    audio, seen = [], set()
    for a in (info or {}).get("audio") or []:
        code = _l2(a.get("lang"))
        if code in seen:
            continue
        seen.add(code)
        codec = _CODECS.get((a.get("codec") or "").lower(), (a.get("codec") or "").upper())
        parts = [x for x in (codec, _chan(a.get("channels")) or (f"{a['channels']}ch" if a.get("channels") else "")) if x]
        label = (i18n.tr("lang." + code) if code else "") or (a.get("lang") if a.get("lang") not in (None, "", "und") else i18n.tr("det.unknown"))
        audio.append((code, f"{label} ({' '.join(parts)}{' + Atmos' if 'atmos' in (a.get('title') or '').lower() else ''})" if parts else label))
    want_a = pf.get("audio_lang") or (up["audio_lang"] if auto else "")
    sel_a = want_a if any(v == want_a for v, _ in audio) else (audio[0][0] if audio else "")
    subs, seen = [], set()
    tracks = [(s.get("lang"), s.get("title")) for s in embedded_subs(info)]
    try:
        tracks += [(s["lang"], s["title"]) for s in external_subs(path)]
    except OSError:
        pass
    for lang, title in tracks:
        code = _l2(lang) or _l2(title)
        if code and code not in seen:
            seen.add(code)
            subs.append((code, i18n.tr("lang." + code)))
    mode = pf.get("sub_mode") or (up["sub_mode"] if auto else "")
    want_s = pf.get("sub_lang") or (up["sub_lang"] if auto else "")
    sel_s = want_s if mode != "off" and any(v == want_s for v, _ in subs) else "off"
    return audio, sel_a, [("off", i18n.tr("det.off"))] + subs, sel_s


@bp.route("/episode/<int:eid>")
@login_required
def episode(eid):
    """Detalhe do episódio (36.1): abre ao clicar no episódio na temporada; o ▶ da miniatura continua indo direto ao player."""
    pid = session["profile_id"]
    with get_db() as conn:
        e = conn.execute("SELECT * FROM episodes WHERE id = ?", (eid,)).fetchone()
        m = conn.execute(
            "SELECT m.*, l.type FROM media m JOIN libraries l ON l.id = m.library_id WHERE m.id = ?", (e["media_id"],)
        ).fetchone() if e else None
        if not m or m["type"] != "show" or not can_access(session["user_id"], m["library_id"]):
            abort(404)
        lib = conn.execute("SELECT id, name, prefs FROM libraries WHERE id = ?", (m["library_id"],)).fetchone()
        prog = conn.execute(
            "SELECT position, watched FROM progress WHERE profile_id = ? AND item_type = 'episode' AND item_id = ?", (pid, eid)
        ).fetchone()
        sibs = conn.execute(
            "SELECT id, season, episode, title FROM episodes WHERE media_id = ? ORDER BY season = 0, season, episode", (m["id"],)
        ).fetchall()
        crew = conn.execute(
            "SELECT p.id, p.name, c.role FROM credits c JOIN people p ON p.id = c.person_id "
            "WHERE c.episode_id = ? AND c.role IN ('director', 'writer') ORDER BY c.role = 'writer', c.ord", (eid,)
        ).fetchall()
    ids = [x["id"] for x in sibs]
    i = ids.index(eid)
    try:
        info = json.loads(e["info"]) if e["info"] else None
    except ValueError:
        info = None
    dur = (info or {}).get("duration") or 0
    pos = prog["position"] if prog and prog["position"] > RESUME_MIN else 0
    watched = bool(prog and prog["watched"])
    pct = min(99.0, pos / dur * 100) if pos and dur and not watched else 0
    extras = detail_extras(m, "show")
    extras["related"] = []  # séries relacionadas não fazem parte da página do episódio
    have = {c["id"] for c in extras["cast"]}
    extras["cast"] += [{"id": c["id"], "name": c["name"], "role": c["role"], "label": _role(c["role"])} for c in crew if c["id"] not in have]
    audio, sel_a, subs, sel_s = _track_options(e["path"], info, _prefs(m["id"], e["season"]))
    v = (info or {}).get("video") or {}
    return render_template(
        "episode.html", e=e, m=m, lib=lib, watched=watched, pct=pct, left=fmt_hm(dur - pos) if pct else "",
        cert=e["content_rating"] or m["content_rating"], air=_fmt_date(e["air_date"]), runtime_hm=fmt_hm(dur),
        imdb=e["imdb_rating"], tmdb_pct=round(e["rating"] * 10) if e["rating"] else None,
        directors=[c for c in crew if c["role"] == "director"], writers=[c for c in crew if c["role"] == "writer"],
        video=(f"{v['height']}p" if v.get("height") else "") + (f" ({ {'h264': 'H.264', 'hevc': 'H.265'}.get(v['codec'].lower(), v['codec'].upper()) })" if v.get("codec") else "") + (f" · {hdr_label(info)}" if hdr_label(info) else ""),
        audio=audio, sel_a=sel_a, subs=subs, sel_s=sel_s,
        prev_id=ids[i - 1] if i > 0 else None, next_id=ids[i + 1] if i + 1 < len(ids) else None,
        season_eps=[x for x in sibs if x["season"] == e["season"]],
        in_list=in_list(m["id"]), stars=get_stars("episode", eid), **extras,
    )


def _season_data(mid, n):
    """Série, biblioteca e episódios da temporada `n` com o estado do perfil (404 se não existir/sem acesso)."""
    with get_db() as conn:
        m = conn.execute(
            "SELECT m.*, l.type FROM media m JOIN libraries l ON l.id = m.library_id WHERE m.id = ?", (mid,)
        ).fetchone()
        if not m or m["type"] != "show" or not can_access(session["user_id"], m["library_id"]):
            abort(404)
        lib = conn.execute("SELECT id, name FROM libraries WHERE id = ?", (m["library_id"],)).fetchone()
        rows = conn.execute(
            "SELECT e.id, e.season, e.episode, e.title, e.info, COALESCE(p.position, 0) AS position, "
            "COALESCE(p.watched, 0) AS watched FROM episodes e "
            "LEFT JOIN progress p ON p.item_type = 'episode' AND p.item_id = e.id AND p.profile_id = ? "
            "WHERE e.media_id = ? ORDER BY e.season, e.episode",
            (session["profile_id"], mid),
        ).fetchall()
    seasons = sorted({r["season"] for r in rows}, key=lambda x: (x == 0, x))  # especiais por último
    if n not in seasons:
        abort(404)
    eps = []
    for r in rows:
        if r["season"] != n:
            continue
        pos = r["position"] if r["position"] > RESUME_MIN else 0
        try:
            dur = (json.loads(r["info"]) if r["info"] else {}).get("duration") or 0
        except ValueError:
            dur = 0
        eps.append({
            "id": r["id"], "season": n, "episode": r["episode"], "title": r["title"], "position": pos,
            "watched": bool(r["watched"]), "pct": min(100, pos / dur * 100) if dur and pos else 0,
        })
    return m, lib, seasons, eps


@bp.route("/show/<int:mid>/season/<int:n>")
@login_required
def season(mid, n):
    """Página da temporada: cabeçalho da série + grade de episódios (still 16:9)."""
    m, lib, seasons, eps = _season_data(mid, n)
    with get_db() as conn:
        srow = conn.execute("SELECT id, title, overview FROM seasons WHERE media_id = ? AND season = ?", (mid, n)).fetchone()
    i = seasons.index(n)
    first_open = next((e for e in eps if not e["watched"]), None)
    return render_template(
        "season.html", prefs=_prefs(mid, n), m=m, lib=lib, n=n, eps=eps, srow=srow, in_list=in_list(mid),
        stars=get_stars("season", srow["id"]) if srow else 0, play=first_open or (eps[0] if eps else None),
        season_pct=(lambda d, t: d / t * 100 if t and 0 < d < t else 0)(sum(1 for e in eps if e["watched"]), len(eps)),
        all_seen=bool(eps) and first_open is None, started=any(e["watched"] or e["position"] for e in eps),
        prev_n=seasons[i - 1] if i > 0 else None, next_n=seasons[i + 1] if i + 1 < len(seasons) else None, seasons=seasons,
    )


@bp.route("/show/<int:mid>/season/<int:n>/play")
@login_required
def season_play(mid, n):
    """Play (próximo não assistido) ou Aleatório (?random=1) dentro da temporada."""
    import random

    m, lib, seasons, eps = _season_data(mid, n)
    if not eps:
        return redirect(f"/show/{mid}/season/{n}")
    if request.args.get("random") == "1":
        ep = random.choice(eps)
    else:
        ep = next((e for e in eps if not e["watched"]), eps[0])
    return redirect(f"/watch/episode/{ep['id']}{_fwd()}")


@bp.route("/show/<int:mid>/random")
@login_required
def show_random(mid):
    """Aleatório: abre um episódio qualquer da série (ignora especiais quando há temporadas regulares)."""
    import random

    with get_db() as conn:
        m = conn.execute(
            "SELECT m.library_id, l.type FROM media m JOIN libraries l ON l.id = m.library_id WHERE m.id = ?", (mid,)
        ).fetchone()
        if not m or m["type"] != "show" or not can_access(session["user_id"], m["library_id"]):
            abort(404)
        eps = conn.execute("SELECT id, season FROM episodes WHERE media_id = ?", (mid,)).fetchall()
    if not eps:
        return redirect(f"/show/{mid}")
    pool = [e for e in eps if e["season"] != 0] or eps
    return redirect(f"/watch/episode/{random.choice(pool)['id']}{_fwd()}")


@bp.route("/watch/<kind>/<int:item_id>")
@login_required
def watch(kind, item_id):
    """Player em tela cheia (hls.js): áudio, legendas, qualidade, progresso e próximo episódio."""
    get_item(kind, item_id)  # valida acesso/arquivo
    with get_db() as conn:
        if kind == "movie":
            m = conn.execute("SELECT library_id, title, original_title, year FROM media WHERE id = ?", (item_id,)).fetchone()
            title, sub, back = display_title(m["library_id"], m["title"], m["original_title"]), str(m["year"] or ""), f"/movie/{item_id}"
            pf = _prefs(item_id)
        else:
            e = conn.execute(
                "SELECT e.season, e.episode, e.title, m.title AS show, m.original_title AS orig, m.library_id AS lid, m.id AS mid "
                "FROM episodes e JOIN media m ON m.id = e.media_id WHERE e.id = ?",
                (item_id,),
            ).fetchone()
            title, back = display_title(e["lid"], e["show"], e["orig"]), f"/show/{e['mid']}?season={e['season']}"
            pf = _prefs(e["mid"], e["season"])
            sub = f"T{e['season']} · E{e['episode']}" + (f" - {e['title']}" if e["title"] else "")
    up = user_prefs()
    auto = up["auto"]  # padrão da conta só vale com a seleção automática ligada e sem preferência própria do item
    audio = request.args.get("audio") or pf.get("audio_lang") or (up["audio_lang"] if auto else "")
    subl = request.args.get("sub") or pf.get("sub_lang") or (up["sub_lang"] if auto else "")
    mode = pf.get("sub_mode") or (up["sub_mode"] if auto else "")
    return render_template("watch.html", kind=kind, item_id=item_id, title=title, sub=sub, back=back,
                           pref_audio=audio, pref_sub=subl, pref_submode=mode,
                           pref_sdh=up["sdh"] if auto else "", pref_forced=up["forced"] if auto else "",
                           skip_intro=up["skip_intro"], auto_next=up["auto_next"], sub_style={k: up[k] for k in ("sub_size", "sub_color", "sub_bg", "sub_pos")}, sub_opts={k: SETTINGS[k][1] for k in ("sub_size", "sub_color", "sub_bg", "sub_pos")})
