"""32.3: motor das fileiras do Início. Cada fileira é registrada com `@row(...)`; o motor aplica ordem, preferências do
perfil (`home_prefs`), mínimo/máximo, dedupe entre fileiras e o limite de 12 fileiras. As etapas 32.4–32.7 só registram provedores."""
import json
import threading
import time

from flask import Blueprint, jsonify, render_template_string, request, session

from server.auth import login_required
from server import i18n
from server.i18n import E, jerr
from server.db import fold, get_db, lib_prefs
from server.libraries import visible_libraries
from server.libraries import get_setting

bp = Blueprint("home_rows", __name__)

MAX_ROWS = 12  # fileiras no Início
MAX_ITEMS = 20  # itens por fileira
MAX_REPEAT = 2  # o mesmo item não aparece em mais de 2 fileiras
KINDS = ("poster", "wide", "playlist")

# ordem padrão (de cima para baixo); chaves fora da lista vão para o fim, na ordem de registro
ORDER = [
    "continue", "on_deck", "mylist", "new_episodes", "because_watched",
    "tmdb_movie_now_playing", "tmdb_tv_airing_today", "tmdb_tv_on_the_air", "tmdb_movie_popular", "tmdb_tv_popular",
    "tmdb_movie_top_rated", "tmdb_tv_top_rated", "tmdb_trending",
    "recent_movies", "recent_shows", "recent_videos", "genre_1", "genre_2", "top_server", "collections", "playlists",
]

# 32.7: título pt-BR das fileiras de gênero (chave = nome do gênero sem acento e em minúsculas; inclui os nomes em inglês). Edite à vontade.
GENRE_TITLES = {
    "terror": "home.genre.horror", "horror": "home.genre.horror",
    "comedia": "home.genre.comedy", "comedy": "home.genre.comedy",
    "ficcao cientifica": "home.genre.scifi", "science fiction": "home.genre.scifi", "sci-fi & fantasy": "home.genre.scifi",
    "acao": "home.genre.action", "action": "home.genre.action", "acao e aventura": "home.genre.action", "action & adventure": "home.genre.action",
    "animacao": "home.genre.family", "animation": "home.genre.family",
    "drama": "home.genre.drama",
    "documentario": "home.genre.documentary", "documentary": "home.genre.documentary",
}


def genre_title(name):
    """Título da fileira do gênero; gênero fora da tabela usa o próprio nome."""
    k = GENRE_TITLES.get(fold(name).strip())
    return i18n.tr(k) if k else name


REGISTRY = {}  # key -> {key, title, kind, provider, min, max}  ou  {expand: f(ctx) -> [spec]} (fileiras dinâmicas, ex.: uma por biblioteca)


def spec(key, title, kind, provider, min_items=1, max_items=MAX_ITEMS):
    return {"key": key, "title": title, "kind": kind, "provider": provider, "min": min_items, "max": max_items}


def row(key, title, kind="poster", min_items=1, max_items=MAX_ITEMS):
    """Registra uma fileira. `provider(ctx)` devolve a lista de itens (dict com `uid` único por item do acervo, ex. \"m:12\");
    `title` pode ser texto ou função `f(ctx, items)`. Provedor que não tem o que mostrar devolve []."""
    if kind not in KINDS:
        raise ValueError(kind)

    def deco(fn):
        REGISTRY[key] = spec(key, title, kind, fn, min_items, max_items)
        return fn
    return deco


def expand(key):
    """Registra uma posição da ordem padrão cujas fileiras dependem do contexto: `fn(ctx)` devolve [spec(...)]."""
    def deco(fn):
        REGISTRY[key] = {"expand": fn}
        return fn
    return deco


class Ctx:
    """Contexto de uma montagem: usuário, perfil e bibliotecas liberadas e visíveis no Início (28.6)."""

    def __init__(self, user_id, profile_id):
        self.user_id, self.profile_id = user_id, profile_id
        shown = [l for l in visible_libraries(user_id) if lib_prefs(l)["visibility"] == "all"]
        self.libs = {l["id"]: l["type"] for l in shown if l["type"] != "video"}  # 34.7: vídeos ficam fora das fileiras TMDB/gênero/uso
        self.video_libs = {l["id"]: l["name"] for l in shown if l["type"] == "video"}
        with get_db() as conn:
            self.merge_recent = get_setting(conn, "merge_recent", "0") == "1"  # 28.8
        self.now = time.time()


def _prefs(conn, profile_id):
    r = conn.execute('SELECT hidden, "order" FROM home_prefs WHERE profile_id = ?', (profile_id,)).fetchone()

    def load(v):
        try:
            v = json.loads(v) if v else []
        except ValueError:
            return []
        return [k for k in v if isinstance(k, str)] if isinstance(v, list) else []
    return (load(r["hidden"]), load(r["order"])) if r else ([], [])


def specs_for(ctx):
    """Fileiras disponíveis no contexto, na ordem padrão: {key: spec}."""
    pos = {k: i for i, k in enumerate(ORDER)}
    found = []
    for n, (key, r) in enumerate(REGISTRY.items()):
        subs = r["expand"](ctx) if "expand" in r else [r]
        for m, sp in enumerate(subs):
            found.append(((pos.get(key, len(ORDER) + n), m), dict(sp, group=key)))
    found.sort(key=lambda t: t[0])
    return {sp["key"]: sp for _, sp in found}


def ordered_keys(specs, order=()):
    """Chaves das fileiras: primeiro as da ordem escolhida pelo perfil, depois as da ordem padrão."""
    mine = [k for k in order if k in specs]
    return mine + [k for k in specs if k not in mine]


# ---- 39.1: layout global do Início (aba Destaques das configurações do administrador) ----
LAYOUT_KEY = "home_layout"
LAYOUT_MAX_ROWS = 40
TMDB_KEYS = [k for k in ORDER if k.startswith("tmdb_")]  # pool das fileiras do TMDB, na ordem padrão
SLOT = "tmdb_slot_"  # TMDB1, TMDB2… = a 1ª, 2ª… fileira do pool que tiver itens no servidor
GROUPS = [k for k in ORDER if not k.startswith("tmdb_")]
LABELS = {  # nome de cada seção na aba Destaques
    "continue": "hl.sec.continue", "on_deck": "hl.sec.on_deck", "mylist": "hl.sec.mylist",
    "new_episodes": "hl.sec.new_episodes", "because_watched": "hl.sec.because_watched",
    "recent_movies": "hl.sec.recent_movies", "recent_shows": "hl.sec.recent_shows",
    "recent_videos": "hl.sec.recent_videos", "genre_1": "hl.sec.genre_1", "genre_2": "hl.sec.genre_2",
    "top_server": "hl.sec.top_server", "collections": "hl.sec.collections", "playlists": "hl.sec.playlists",
}


def default_layout():
    """Layout padrão: ordem de `ORDER` com as 8 fileiras do TMDB como TMDB1…TMDB8, tudo ligado, no máximo 12 fileiras."""
    order, done = [], False
    for k in ORDER:
        if k.startswith("tmdb_"):
            if not done:
                order += [f"{SLOT}{i}" for i in range(1, len(TMDB_KEYS) + 1)]
                done = True
        else:
            order.append(k)
    return {"order": order, "hidden": [], "tmdb": len(TMDB_KEYS), "max_rows": MAX_ROWS}


def clean_layout(d):
    """Valida e normaliza um layout (dict qualquer → dict seguro). Levanta ValueError se for inválido."""
    if not isinstance(d, dict):
        raise ValueError(E("err.dados_invalidos"))
    n, mx = d.get("tmdb"), d.get("max_rows")
    if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= len(TMDB_KEYS):
        raise ValueError(E("err.quantidade_fileiras_tmdb_invalida"))
    if isinstance(mx, bool) or not isinstance(mx, int) or not 1 <= mx <= LAYOUT_MAX_ROWS:
        raise ValueError(E("err.max_fileiras", max=LAYOUT_MAX_ROWS))
    valid = set(GROUPS) | {f"{SLOT}{i}" for i in range(1, n + 1)}
    order = d.get("order")
    hidden = d.get("hidden")
    if not isinstance(order, list) or not isinstance(hidden, list) or any(not isinstance(k, str) for k in order + hidden):
        raise ValueError(E("err.dados_invalidos"))
    order = [k for k in dict.fromkeys(order) if k in valid]
    order += [k for k in default_layout()["order"] if k in valid and k not in order]  # seção que faltou entra no fim
    return {"order": order, "hidden": [k for k in dict.fromkeys(hidden) if k in valid], "tmdb": n, "max_rows": mx}


def load_layout(conn):
    """Layout salvo pelo administrador (None = nunca salvo: vale o comportamento padrão de sempre)."""
    from server.libraries import get_setting
    raw = get_setting(conn, LAYOUT_KEY)
    if not raw:
        return None
    try:
        return clean_layout(json.loads(raw))
    except ValueError:
        return None


def save_layout(conn, layout):
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (LAYOUT_KEY, json.dumps(layout, ensure_ascii=False)))
    clear_cache()


def reset_layout(conn):
    conn.execute("DELETE FROM settings WHERE key = ?", (LAYOUT_KEY,))
    clear_cache()


def _plan(specs, layout, order, hidden):
    """Lista das fileiras a tentar, na ordem final: [(key_de_saida, spec ou None, slot)]. `None` = slot do TMDB, resolvido depois."""
    if not layout:
        return [(k, specs[k], 0) for k in ordered_keys(specs, order) if k not in hidden]
    plan, groups = [], {}
    for k, sp in specs.items():
        groups.setdefault(sp["group"], []).append(sp)
    for tok in order:
        if tok in hidden:
            continue
        if tok.startswith(SLOT):
            plan.append((tok, None, int(tok[len(SLOT):])))
        else:
            plan += [(sp["key"], sp, 0) for sp in groups.get(tok, [])]
    return plan


def build_rows(user_id, profile_id):
    """Fileiras do Início do perfil: [{key, title, type, items}], já com dedupe, mínimo, máximo e limite de fileiras.
    Com layout salvo (39.1) valem a ordem, as seções ligadas, os slots TMDB1… e o máximo de fileiras do administrador."""
    ctx = Ctx(user_id, profile_id)
    with get_db() as conn:
        hidden, order = _prefs(conn, profile_id)
        layout = load_layout(conn)
    if layout:
        hidden = list(dict.fromkeys(layout["hidden"] + hidden))
        order = order or layout["order"]
        limit = layout["max_rows"]
    else:
        limit = MAX_ROWS
    specs = specs_for(ctx)
    if layout:  # as fileiras do TMDB só entram pelos slots
        specs = {k: sp for k, sp in specs.items() if k not in TMDB_KEYS}
    memo = {}

    def items_of(sp):
        if sp["key"] not in memo:
            try:
                memo[sp["key"]] = list(sp["provider"](ctx) or [])
            except Exception:  # uma fileira com defeito não derruba o Início
                memo[sp["key"]] = []
        return memo[sp["key"]]

    plan = _plan(specs, layout, order, hidden)
    if layout and any(sp is None for _, sp, _ in plan):  # TMDBn = n-ésima fileira do pool com itens suficientes no servidor
        pool = [r for r in (REGISTRY[k] for k in TMDB_KEYS if k in REGISTRY) if len(items_of(r)) >= r["min"]]
        plan = [(k, (pool[n - 1] if sp is None and n <= len(pool) else sp), n) for k, sp, n in plan]
        plan = [(k, sp, n) for k, sp, n in plan if sp is not None]
    used, out = {}, []
    for _, sp, _n in plan:
        if len(out) >= limit:
            break
        keep = []
        for it in items_of(sp):
            uid = it.get("uid")
            if uid is not None and used.get(uid, 0) >= MAX_REPEAT:
                continue
            keep.append(it)
            if len(keep) >= sp["max"]:
                break
        if len(keep) < sp["min"]:
            continue
        for it in keep:
            if it.get("uid") is not None:
                used[it["uid"]] = used.get(it["uid"], 0) + 1
        title = sp["title"](ctx, keep) if callable(sp["title"]) else sp["title"]
        if isinstance(title, str) and title.startswith("home.row."):  # 59.10: título da fileira = chave do catálogo
            title = i18n.tr(title)
        out.append({"key": sp["key"], "title": title, "type": sp["kind"], "items": keep})
    return out


_cache = {}
_cache_lock = threading.Lock()
CACHE_TTL = 15  # s: o Início carrega as fileiras 4+ uma a uma; todas reaproveitam a montagem da página


def clear_cache():
    with _cache_lock:
        _cache.clear()


def build_rows_cached(user_id, profile_id, fresh=False):
    """`build_rows` com cache de 15 s por perfil (`fresh=True` refaz e atualiza o cache, usado ao abrir o Início)."""
    k = (user_id, profile_id)
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(k)
    if hit and not fresh and now - hit[0] < CACHE_TTL:
        return hit[1]
    rows = build_rows(user_id, profile_id)
    with _cache_lock:
        for old in [x for x, v in _cache.items() if now - v[0] > CACHE_TTL * 4]:
            _cache.pop(old, None)
        _cache[k] = (now, rows)
    return rows


def _pct(r):
    """Barra de progresso do pôster de filme: posição / duração (só em andamento, acima de 5 s; 0 se não souber a duração)."""
    if r["seen"] or not r["pos"] or r["pos"] <= 5:
        return 0
    try:
        dur = (json.loads(r["info"]) if r["info"] else {}).get("duration") or 0
    except ValueError:
        return 0
    return min(99, int(r["pos"] / dur * 100)) if dur and r["eps"] == 0 else 0


def poster_items(conn, ctx, ids):
    """Cards de pôster (filme/série) na ordem de `ids`, só de bibliotecas liberadas e visíveis no Início; `watched` do perfil."""
    ids = [i for i in dict.fromkeys(ids)]
    if not ids or not ctx.libs:
        return []
    qi = ",".join("?" * len(ids))
    rows = conn.execute(
        "SELECT m.id, dtitle(m.library_id, m.title, m.original_title) AS shown, m.year, m.library_id, "
        "(SELECT COUNT(*) FROM episodes e WHERE e.media_id = m.id) AS eps, "
        "(SELECT COUNT(*) FROM episodes e JOIN progress ep ON ep.profile_id = ? AND ep.item_type = 'episode' AND ep.item_id = e.id "
        "AND ep.watched = 1 WHERE e.media_id = m.id) AS eps_seen, "
        "COALESCE((SELECT pm.watched FROM progress pm WHERE pm.profile_id = ? AND pm.item_type = 'movie' AND pm.item_id = m.id), 0) AS seen, "
        "COALESCE((SELECT pm.position FROM progress pm WHERE pm.profile_id = ? AND pm.item_type = 'movie' AND pm.item_id = m.id), 0) AS pos, m.info "
        f"FROM media m WHERE m.id IN ({qi})", (ctx.profile_id, ctx.profile_id, ctx.profile_id, *ids)).fetchall()
    by = {r["id"]: r for r in rows if r["library_id"] in ctx.libs}
    out = []
    for i in ids:
        r = by.get(i)
        if not r:
            continue
        t = ctx.libs[r["library_id"]]
        out.append({"uid": f"m:{i}", "id": i, "type": t, "title": r["shown"], "year": r["year"], "lib": r["library_id"], "pct": _pct(r),
                    "watched": bool(r["seen"]) if t == "movie" else bool(r["eps"] and r["eps_seen"] == r["eps"])})
    return out


def _left(i):
    """54.3: \"1h 2m restantes\" do Continuar assistindo (vazio sem duração)."""
    if not i.get("duration"):
        return None
    m = max(1, int((i["duration"] - i["position"]) // 60))
    h, m = divmod(m, 60)
    return (f"{h}h {m}m" if h else f"{m}m") + " restantes"


def hero_items(row, limit=8):
    """54.2: destaque do celular = itens da PRIMEIRA fileira do Início (a ordem vem da tela Destaques do Início).
    Só filmes/séries; devolve [{id, type, title, year, genre, bd, logo}]."""
    if not row or row.get("type") in ("wide", "playlist"):
        return []
    its = [i for i in row["items"] if i.get("type") in ("movie", "show")][:limit]
    if not its:
        return []
    with get_db() as conn:
        qi = ",".join("?" * len(its))
        by = {r["id"]: r for r in conn.execute(f"SELECT id, year, genres, backdrop, logo FROM media WHERE id IN ({qi})", [i["id"] for i in its])}
    out = []
    for i in its:
        r = by.get(i["id"])
        if not r:
            continue
        out.append({"id": i["id"], "type": i["type"], "title": i["title"], "year": r["year"] or i.get("year"),
                    "genre": ((r["genres"] or "").split(",")[0].strip() or None),
                    "bd": f"/backdrop/{i['id']}" if r["backdrop"] else f"/poster/{i['id']}", "logo": bool(r["logo"])})
    return out


# ---- fileiras de uso (32.4) ----
@row("continue", "home.row.continue")
def _continue(ctx):
    """Capa do filme ou da série (como as outras fileiras); episódio em andamento mostra a série, o título e T · E, e o ▶ abre o episódio.
    Vídeo (biblioteca Outros Vídeos) não tem capa: usa a miniatura 16:9."""
    from server.progress import continue_watching
    out = []
    for i in continue_watching(ctx.user_id, ctx.profile_id, home=True):
        pct = min(100, int(i["position"] / i["duration"] * 100)) if i.get("duration") else 0
        if i["kind"] == "episode":
            out.append({"uid": f"m:{i['media_id']}", "id": i["media_id"], "type": "show", "title": i["show"], "year": None, "lib": i.get("lib"),
                        "season": i["season"], "episode": i["episode"], "ep_title": i["title"], "episode_id": i["id"], "pct": pct, "watched": False,
                        "bd": f"/backdrop/{i['media_id']}", "left": _left(i)})
        elif i.get("lib") in ctx.video_libs:  # 34.7: vídeo = miniatura (frame)
            out.append({"uid": f"m:{i['media_id']}", "id": i["media_id"], "type": "video", "kind": "movie", "title": i["title"], "year": None,
                        "lib": i["lib"], "still": f"/thumb/{i['media_id']}", "pct": pct, "watched": False})
        else:
            out.append({"uid": f"m:{i['media_id']}", "id": i["media_id"], "type": "movie", "title": i["title"], "year": i["year"], "lib": i["lib"],
                        "pct": pct, "watched": False, "bd": f"/backdrop/{i['media_id']}", "left": _left(i)})
    return out


@row("mylist", "home.row.mylist")
def _mylist(ctx):
    from server.mylist import my_list_items
    return [dict(i, uid=f"m:{i['id']}") for i in my_list_items(ctx.profile_id, ctx.user_id, home=True)]


from server import home_library, home_tmdb, home_usage  # noqa: E402,F401  (registram as fileiras de uso, do TMDB e do acervo)


# ---- rotas ----
def _profile():
    pid = session.get("profile_id")
    if not pid:
        return None
    with get_db() as conn:
        ok = conn.execute("SELECT 1 FROM profiles WHERE id = ? AND user_id = ?", (pid, session["user_id"])).fetchone()
    return pid if ok else None


@bp.route("/home/rows")
@login_required
def rows():
    pid = _profile()
    if not pid:
        return jerr("err.perfil_nao_selecionado", 400)
    return jsonify(rows=build_rows(session["user_id"], pid))


@bp.route("/home/row/<key>")
@login_required
def one_row(key):
    """Uma fileira (JSON). Com `?html=1` devolve também os cards já renderizados (`html`) para o Início montar sem recarregar."""
    pid = _profile()
    if not pid:
        return jerr("err.perfil_nao_selecionado", 400)
    for r in build_rows_cached(session["user_id"], pid):
        if r["key"] == key:
            out = {"row": r}
            if request.args.get("html") == "1":
                with get_db() as conn:
                    u = conn.execute("SELECT is_admin FROM users WHERE id = ?", (session["user_id"],)).fetchone()
                out["html"] = render_template_string(
                    '{% from "_home_cards.html" import cards %}{{ cards(row, admin) }}', row=r, admin=bool(u and u["is_admin"]))
            return jsonify(out)
    return jerr("err.fileira_nao_encontrada", 404)
