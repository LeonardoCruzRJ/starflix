"""Página do ator/diretor (37.x): dados do TMDB (buscados na 1ª visita), filmografia e itens do servidor."""
import json
import threading
import time
from datetime import date

import requests
from flask import Blueprint, abort, render_template, session

import config
from server import i18n, metadata
from server.auth import login_required
from server.db import get_db
from server.libraries import _placeholder, can_access, visible_libraries
from server.pcts import pct_map

bp = Blueprint("people", __name__)

_lock = threading.Lock()
RETRY_S = 600            # falha de rede/TMDB: tenta de novo só depois de 10 min
STALE_S = 30 * 86400     # dados com mais de 30 dias são renovados em segundo plano
GENRE_APPEARANCE = {10767, 10764, 10763}  # Talk, Reality, News: aparições "como Self"
ROLE_NAME = {"cast": "det.role.cast", "director": "det.role.director", "writer": "det.role.writer", "producer": "det.role.producer"}  # chaves do catálogo
DEPT_ROLE = {"Acting": "cast", "Directing": "director", "Writing": "writer", "Production": "producer"}
WRITER_JOBS = {"Writer", "Screenplay", "Story", "Novel", "Teleplay", "Creator", "Characters", "Original Story"}
PRODUCER_JOBS = {"Producer", "Executive Producer", "Co-Producer"}
JOB_KEY = {j: "person.job." + j.lower().replace(" ", "_").replace("-", "_") for j in (
    "Director", "Producer", "Executive Producer", "Co-Producer", "Writer", "Screenplay", "Story", "Creator", "Novel", "Teleplay", "Characters", "Original Story", "Associate Producer", "Executive Music Producer", "Music Producer", "Co-Executive Producer", "Thanks", "Special Thanks", "Archive Footage", "Dedicatee", "Original Music Composer", "Editor", "Director of Photography")}


def job_label(job):
    """Cargo traduzido no idioma da requisição (cargo desconhecido volta como veio do TMDB)."""
    return i18n.tr(JOB_KEY[job]) if job in JOB_KEY else job


TAB_ORDER = (("cast", "det.role.cast"), ("self", "person.tab.self"), ("director", "det.role.director"), ("writer", "det.role.writer"),
             ("producer", "det.role.producer"), ("other", "person.tab.extra"))  # chaves do catálogo


def fmt_date(iso):
    """'1974-08-20' → data por extenso no idioma ativo (vazio se inválida)."""
    return i18n.fmt_date(iso)


def age(birth, death=None):
    try:
        b = date(*(int(x) for x in birth.split("-")))
        e = date(*(int(x) for x in death.split("-"))) if death else date.today()
    except (ValueError, AttributeError, TypeError):
        return None
    return e.year - b.year - ((e.month, e.day) < (b.month, b.day))


def _year(d):
    return int(d[:4]) if d and d[:4].isdigit() else None


def _compact(cc):
    """combined_credits do TMDB → listas enxutas (elenco e equipe) guardadas em people.filmography."""
    cast, crew, seen = [], [], set()
    for c in (cc or {}).get("cast") or []:
        if c.get("media_type") not in ("movie", "tv") or c.get("id") is None:
            continue
        key = (c["media_type"], c["id"], c.get("character") or "")
        if key in seen:
            continue
        seen.add(key)
        cast.append({
            "id": c["id"], "mt": c["media_type"], "t": c.get("title") or c.get("name") or "",
            "y": _year(c.get("release_date") or c.get("first_air_date")), "ch": (c.get("character") or "").strip(),
            "n": c.get("episode_count") or 0, "v": c.get("vote_count") or 0, "p": c.get("popularity") or 0,
            "g": c.get("genre_ids") or [], "poster": c.get("poster_path"),
        })
    seen = set()
    for c in (cc or {}).get("crew") or []:
        if c.get("media_type") not in ("movie", "tv") or c.get("id") is None or not c.get("job"):
            continue
        key = (c["media_type"], c["id"], c["job"])
        if key in seen:
            continue
        seen.add(key)
        crew.append({
            "id": c["id"], "mt": c["media_type"], "t": c.get("title") or c.get("name") or "",
            "y": _year(c.get("release_date") or c.get("first_air_date")), "job": c["job"], "dept": c.get("department") or "",
            "n": c.get("episode_count") or 0, "v": c.get("vote_count") or 0, "p": c.get("popularity") or 0,
            "g": c.get("genre_ids") or [], "poster": c.get("poster_path"),
        })
    return {"cast": cast, "crew": crew}


def _wiki_bio(code, wikidata_id):
    """57.5: introdução do artigo da Wikipédia no idioma `code` (via Wikidata); "" se não houver ou der erro."""
    if not wikidata_id or not code:
        return ""
    h = {"User-Agent": "StarFlix/1.0 (servidor de video local)"}
    try:
        r = requests.get("https://www.wikidata.org/w/api.php", headers=h, timeout=10, params={
            "action": "wbgetentities", "ids": wikidata_id, "props": "sitelinks", "sitefilter": code + "wiki", "format": "json"})
        r.raise_for_status()
        title = (((r.json().get("entities") or {}).get(wikidata_id) or {}).get("sitelinks") or {}).get(code + "wiki", {}).get("title")
        if not title:
            return ""
        r = requests.get(f"https://{code}.wikipedia.org/w/api.php", headers=h, timeout=10, params={
            "action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1, "redirects": 1, "titles": title, "format": "json"})
        r.raise_for_status()
        pages = (r.json().get("query") or {}).get("pages") or {}
        txt = next(iter(pages.values()), {}).get("extract") or ""
    except (requests.RequestException, ValueError, AttributeError):
        return ""
    txt = txt.strip()
    if not txt:
        return ""
    if code == "pt":
        return f"{txt}\n\nDescrição acima do artigo da Wikipédia {title}, licenciada sob CC-BY-SA."
    return f"{txt}\n\nWikipedia: {title} (CC-BY-SA)."


def _bio(tmdb_id, d):
    """57.5: biografia no idioma configurado: TMDB → traduções do TMDB (mesmo idioma, outra região) → Wikipédia do idioma → inglês.
    Devolve (texto, idioma) com idioma = código de 2 letras ou "en" quando caiu no inglês."""
    lang = metadata._lang() or "pt-BR"
    code = lang[:2].lower()
    bio = (d.get("biography") or "").strip()
    if bio:
        return bio, code
    if code != "en":
        try:
            for t in metadata.tmdb_get(f"/person/{tmdb_id}/translations").get("translations") or []:
                tb = ((t.get("data") or {}).get("biography") or "").strip()
                if tb and (t.get("iso_639_1") or "").lower() == code:
                    return tb, code
        except (requests.RequestException, ValueError):
            pass
        bio = _wiki_bio(code, (d.get("external_ids") or {}).get("wikidata_id"))
        if bio:
            return bio, code
        return (metadata.tmdb_get(f"/person/{tmdb_id}", language="en-US").get("biography") or "").strip(), "en"
    return "", code


def fetch_person(pid):
    """Busca no TMDB biografia, datas, redes sociais e filmografia da pessoa; True se gravou. Nunca levanta erro de rede."""
    with _lock:
        with get_db() as conn:
            p = conn.execute("SELECT id, tmdb_id, info_ok FROM people WHERE id = ?", (pid,)).fetchone()
        if not p or not p["tmdb_id"] or not config.TMDB_API_KEY:
            return False
        now = int(time.time())
        try:
            d = metadata.tmdb_get(f"/person/{p['tmdb_id']}", append_to_response="combined_credits,external_ids")
            bio, bio_lang = _bio(p["tmdb_id"], d)
        except (requests.RequestException, ValueError):
            with get_db() as conn:
                conn.execute("UPDATE people SET info_at = ? WHERE id = ?", (now, pid))
            return False
        ext = d.get("external_ids") or {}
        big = None
        if d.get("profile_path"):
            rel = f"people/{pid}_big.jpg"
            if metadata._download(d["profile_path"], "h632", rel):
                big = rel
        with get_db() as conn:
            conn.execute(
                "UPDATE people SET birthday = ?, deathday = ?, bio = ?, dept = ?, imdb_id = ?, instagram = ?, twitter = ?, "
                "photo_big = COALESCE(?, photo_big), filmography = ?, info_ok = 1, info_at = ?, bio_lang = ? WHERE id = ?",
                (d.get("birthday") or None, d.get("deathday") or None, bio or None, d.get("known_for_department"),
                 ext.get("imdb_id") or d.get("imdb_id"), ext.get("instagram_id"), ext.get("twitter_id"), big,
                 json.dumps(_compact(d.get("combined_credits")), ensure_ascii=False, separators=(",", ":")), now, bio_lang, pid),
            )
        return True


def _is_self(c):
    ch = c.get("ch") or ""
    return "self" in ch.lower().split() or ch.lower().startswith(("self", "himself", "herself", "themselves")) \
        or bool(GENRE_APPEARANCE & set(c.get("g") or []))


def _local_map(conn, user_id):
    """{('movie'|'tv', tmdb_id): (id local, 'movie'|'show')} das bibliotecas liberadas ao usuário."""
    libs = [l["id"] for l in visible_libraries(user_id) if l["type"] in ("movie", "show")]
    if not libs:
        return {}
    ph = ",".join("?" * len(libs))
    out = {}
    for r in conn.execute(
        f"SELECT m.id, m.tmdb_id, l.type FROM media m JOIN libraries l ON l.id = m.library_id "
        f"WHERE m.tmdb_id > 0 AND m.library_id IN ({ph}) ORDER BY m.id DESC", libs,
    ):
        out[("movie" if r["type"] == "movie" else "tv", r["tmdb_id"])] = (r["id"], r["type"])
    return out


def _sort_key(x):
    return (0 if x["y"] is None else 1, -(x["y"] or 0), -x["p"])


def _row(c, local, sub):
    loc = local.get((c["mt"], c["id"]))
    return {"y": c["y"], "t": c["t"], "sub": sub, "p": c["p"],
            "url": f"/{loc[1]}/{loc[0]}" if loc else None}


def build(fil, local, dept):
    """Abas da filmografia, subtítulo de papéis e 'Conhecido Por' a partir de people.filmography."""
    cast, crew = fil.get("cast") or [], fil.get("crew") or []
    groups = {k: [] for k, _ in TAB_ORDER}
    for c in cast:
        if _is_self(c):
            groups["self"].append(_row(c, local, i18n.tr("person.as", name=c["ch"]) if c["ch"] else ""))
        else:
            groups["cast"].append(_row(c, local, i18n.tr("person.as", name=c["ch"]) if c["ch"] else ""))
    for c in crew:
        job = c["job"]
        key = "director" if job == "Director" else "writer" if job in WRITER_JOBS else "producer" if job in PRODUCER_JOBS else "other"
        groups[key].append(_row(c, local, "" if key == "director" else job_label(job)))
    tabs = []
    for key, label in TAB_ORDER:
        rows = sorted(groups[key], key=_sort_key)
        if rows:
            tabs.append({"key": key, "label": i18n.tr(label), "rows": rows})
    roles = [i18n.tr(ROLE_NAME[t["key"]]) for t in tabs if t["key"] in ROLE_NAME]
    # Conhecido Por: pela área principal da pessoa (atuação, direção...), os mais votados com pôster
    main = DEPT_ROLE.get(dept or "", "cast")
    pool = {
        "cast": [c for c in cast if not _is_self(c)],
        "director": [c for c in crew if c["job"] == "Director"],
        "writer": [c for c in crew if c["job"] in WRITER_JOBS],
        "producer": [c for c in crew if c["job"] in PRODUCER_JOBS],
    }
    items = pool[main] or pool["cast"] or pool["director"] or pool["writer"] or pool["producer"]
    known, seen = [], set()
    for c in sorted(items, key=lambda c: (-(c["v"] or 0), -(c["p"] or 0))):
        if not c.get("poster") or (c["mt"], c["id"]) in seen:
            continue
        seen.add((c["mt"], c["id"]))
        loc = local.get((c["mt"], c["id"]))
        label = c.get("ch") if "ch" in c else job_label(c.get("job"))
        third = i18n.tr("det.episodes", n=c["n"]) if c["mt"] == "tv" and c["n"] else (str(c["y"]) if c["y"] else "")
        known.append({"id": c["id"], "mt": c["mt"], "t": c["t"], "label": label or "", "third": third,
                      "local": loc[0] if loc else None, "kind": loc[1] if loc else None})
        if len(known) >= 12:
            break
    return tabs, roles, known


def _access(conn, pid):
    libs = [r["library_id"] for r in conn.execute(
        "SELECT DISTINCT m.library_id FROM credits c JOIN media m ON m.id = c.media_id WHERE c.person_id = ?", (pid,))]
    return any(can_access(session["user_id"], lid) for lid in libs)


@bp.route("/people/<int:pid>")
@login_required
def person_page(pid):
    with get_db() as conn:
        p = conn.execute("SELECT * FROM people WHERE id = ?", (pid,)).fetchone()
        if not p or not _access(conn, pid):
            abort(404)
    now = time.time()
    if not p["info_ok"] and p["tmdb_id"] and (not p["info_at"] or now - p["info_at"] > RETRY_S):
        fetch_person(pid)  # 1ª visita: busca no TMDB (≈1–2 s) e já mostra completa
    elif p["info_ok"] and (not p["info_at"] or now - p["info_at"] > STALE_S):
        threading.Thread(target=fetch_person, args=(pid,), daemon=True).start()
    with get_db() as conn:
        p = conn.execute("SELECT * FROM people WHERE id = ?", (pid,)).fetchone()
        local = _local_map(conn, session["user_id"])
        libs = [l["id"] for l in visible_libraries(session["user_id"]) if l["type"] in ("movie", "show")]
        roles_local = [r["role"] for r in conn.execute("SELECT DISTINCT role FROM credits WHERE person_id = ?", (pid,))]
        items = []
        if libs:
            ph = ",".join("?" * len(libs))
            items = conn.execute(
                "SELECT m.id, dtitle(m.library_id, m.title, m.original_title) AS title, m.year, l.type, "
                "COALESCE(pm.watched, 0) AS seen FROM media m JOIN libraries l ON l.id = m.library_id "
                "LEFT JOIN progress pm ON pm.profile_id = ? AND pm.item_type = 'movie' AND pm.item_id = m.id "
                f"WHERE m.library_id IN ({ph}) AND m.id IN (SELECT media_id FROM credits WHERE person_id = ?) "
                "ORDER BY m.year IS NULL, m.year DESC, fold(m.title), m.id",
                (session["profile_id"], *libs, pid),
            ).fetchall()
        pm = pct_map(conn, session["profile_id"], [x["id"] for x in items]) if items else {}
    try:
        fil = json.loads(p["filmography"]) if p["filmography"] else {}
    except ValueError:
        fil = {}
    tabs, roles, known = build(fil, local, p["dept"])
    if not roles:  # sem filmografia do TMDB: papéis das fichas do servidor, depois a área principal
        order = ["cast", "director", "writer", "producer"]
        roles = [i18n.tr(ROLE_NAME[r]) for r in order if r in roles_local] or ([i18n.tr(ROLE_NAME[DEPT_ROLE[p["dept"]]])] if p["dept"] in DEPT_ROLE else [])
    born = fmt_date(p["birthday"])
    yrs = age(p["birthday"], p["deathday"]) if born else None
    social = []
    if p["instagram"]:
        social.append({"ic": "i-instagram", "name": "Instagram", "handle": "@" + p["instagram"], "url": "https://www.instagram.com/" + p["instagram"]})
    if p["twitter"]:
        social.append({"ic": "i-x", "name": "Twitter", "handle": "@" + p["twitter"], "url": "https://twitter.com/" + p["twitter"]})
    return render_template(
        "person.html", p=p, roles=", ".join(roles), born=born, age=yrs, died=fmt_date(p["deathday"]), social=social,
        bio=(p["bio"] or "").strip(), has_big=bool(p["photo_big"] or p["photo"]),
        items=[{**dict(x), "pct": pm.get(x["id"])} for x in items], known=known, tabs=tabs,
    )


@bp.route("/person-art/<int:pid>/<mt>/<int:tid>")
@login_required
def person_art(pid, mt, tid):
    """Pôster (w342) de um título da filmografia: baixado do TMDB na 1ª vez e guardado em data/posters/pk/."""
    from server.images import _send
    if mt not in ("movie", "tv"):
        abort(404)
    with get_db() as conn:
        p = conn.execute("SELECT filmography FROM people WHERE id = ?", (pid,)).fetchone()
        if not p or not _access(conn, pid):
            abort(404)
    try:
        fil = json.loads(p["filmography"]) if p["filmography"] else {}
    except ValueError:
        fil = {}
    entry = next((c for c in (fil.get("cast") or []) + (fil.get("crew") or []) if c["mt"] == mt and c["id"] == tid and c.get("poster")), None)
    if not entry:
        abort(404)
    rel = f"pk/{mt}{tid}.jpg"
    r = _send(rel, max_age=604800)
    if r:
        return r
    if metadata._download(entry["poster"], "w342", rel):
        r = _send(rel, max_age=604800)
        if r:
            return r
    return _placeholder(entry["t"])
