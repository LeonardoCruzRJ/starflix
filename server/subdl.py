"""46.1: legendas do SubDL (https://subdl.com/api-doc), salvas ao lado do vídeo como `<nome>.<idioma>.srt`.

Regras:
- uma legenda por filme/episódio; além dela, a "forçada" (`<nome>.<idioma>.forced.srt`) só quando o arquivo tem áudio no idioma
  configurado (filme dublado) e o SubDL tem uma legenda marcada como forçada;
- nada é baixado se o vídeo já tem legenda no idioma (arquivo ao lado ou faixa de texto embutida);
- exame automático (periódico, biblioteca nova) tenta cada arquivo uma vez; "Examinar arquivos" tenta de novo o que ainda falta, uma vez por exame;
- limites por exame para não gastar a cota (buscas e downloads); erro de rede/cota/chave encerra a etapa sem marcar tentativa.
- 46.3: orçamento diário de buscas (DAILY_MAX, UTC) e bloqueio até o dia virar após 429; "nada encontrado" só é repetido após RETRY_DAYS dias.
"""
import io
import json
import logging
import os
import re
import time
import unicodedata
import zipfile

import requests

import config
from server import scanstate
from server.db import get_db
from server.i18n import E

log = logging.getLogger(__name__)

API = "https://api.subdl.com/api/v1/subtitles"
DL = "https://dl.subdl.com"
MAX_SEARCH = 500     # buscas por exame (a chave grátis tem 2.000 por dia)
DAILY_MAX = 1700     # buscas por dia (UTC), somando todos os exames — deixa folga na cota de 2.000
RETRY_DAYS = 7       # "Examinar arquivos" só tenta de novo um "nada encontrado" com mais de N dias
MAX_DOWNLOAD = 150   # downloads por exame (sem chave paga: 300 por dia por IP)
PAUSE = 0.4          # segundos entre chamadas
MAX_ZIP = 8 * 1024 * 1024
MAX_SRT = 3 * 1024 * 1024
TRIES = 3            # candidatas testadas por legenda

# código SubDL -> (marca no nome do arquivo, idioma-base)
LANGS = {"BR_PT": ("pt-BR", "pt"), "PT": ("pt-PT", "pt"), "EN": ("en", "en"), "ES": ("es", "es"),
         "FR": ("fr", "fr"), "DE": ("de", "de"), "IT": ("it", "it"), "JA": ("ja", "ja"),
         "RU": ("ru", "ru"), "ZH": ("zh", "zh"), "TR": ("tr", "tr")}  # 59.37: os 10 idiomas do StarFlix
ALIASES = {
    "pt": {"pt", "por", "pob", "ptbr", "portuguese", "brazilian", "portugues", "português", "brasil"},
    "en": {"en", "eng", "english"}, "es": {"es", "spa", "esp", "spanish", "espanol", "español"},
    "fr": {"fr", "fra", "fre", "french"}, "de": {"de", "deu", "ger", "german"},
    "it": {"it", "ita", "italian"}, "ja": {"ja", "jpn", "japanese"},
    "ru": {"ru", "rus", "russian", "русский"}, "zh": {"zh", "zho", "chi", "chs", "cht", "chinese", "中文", "简体中文"},
    "tr": {"tr", "tur", "turkish", "türkçe", "turkce"},
}
_FORCED = re.compile(r"forced|for[cç]ad[ao]s?", re.I)
_SXE = re.compile(r"s(\d{1,2})[ ._-]?e(\d{1,3})|(\d{1,2})x(\d{2,3})", re.I)

_day = {"d": "", "n": 0, "blocked": False}  # orçamento do dia, vale para todos os exames (não zera no begin_run)
_run = {"manual": False, "start": 0.0, "search": 0, "download": 0, "errors": 0, "stop": None, "hint": {}}


class Stop(Exception):
    """Cota, chave ou rede: encerra a etapa de legendas deste exame."""


def _roll_day():
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if _day["d"] != today:
        _day.update(d=today, n=0, blocked=False)


def _block():
    """O SubDL disse que a cota do dia acabou: nenhum exame volta a buscar até o dia (UTC) virar."""
    _roll_day()
    _day["blocked"] = True


def begin_run(manual=False):
    """Chamado ao iniciar um exame (scanner.scan_async)."""
    _run.update(manual=bool(manual), start=time.time(), search=0, download=0, errors=0, stop=None, hint={})


# ---------------------------------------------------------------- o que o vídeo já tem

def _is_lang(tag, base):
    t = (tag or "").lower().replace("_", "-")
    return t in ALIASES[base] or t.split("-")[0] in ALIASES[base]


def _info(raw):
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def have(path, info_raw, base):
    """(tem legenda completa, tem forçada) no idioma — arquivo ao lado ou faixa de texto embutida."""
    from server.subtitles import embedded_subs, external_subs
    full = forced = False
    try:
        ext = external_subs(path)
    except OSError:
        ext = []
    for s in ext:
        rest = s.get("lang")
        toks = [t.lower() for t in re.split(r"[._ ]+", rest)] if rest else []
        is_forced = "forced" in toks or bool(_FORCED.search(rest or ""))
        if toks and not any(_is_lang(t, base) for t in toks):
            continue  # legenda de outro idioma
        if is_forced:
            forced = True
        else:
            full = True  # sem marca de idioma (ex.: "Filme.srt") também conta: é legenda do usuário
    for t in embedded_subs(_info(info_raw)):
        if t.get("lang") and not _is_lang(t["lang"], base):
            continue
        if _FORCED.search(t.get("title") or ""):
            forced = True
        elif t.get("lang"):
            full = True
    return full, forced


def audio_in(info_raw, base):
    return any(_is_lang(a.get("lang"), base) for a in _info(info_raw).get("audio") or [] if a.get("lang"))


# ---------------------------------------------------------------- SubDL

def _tokens(text):
    return {t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(t) > 1}


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


def _norm(text):
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", t)


def _call(key, lang, kind, base, extra, manual=False):
    """Uma consulta ao SubDL: (results, subtitles), None se falhou de forma passageira. Levanta Stop em cota/chave/rede."""
    _roll_day()
    if _day["blocked"]:
        raise Stop(E("msg.subdl_cota_diria_do_subdl_j_esgota"))
    if _day["n"] >= DAILY_MAX:
        raise Stop(E("msg.subdl_oramento_dirio_de_buscas_do"))
    if not manual and _run["search"] >= MAX_SEARCH:
        raise Stop(E("msg.subdl_limite_de_buscas_por_exame"))
    if not manual:
        _run["search"] += 1
    _day["n"] += 1
    params = {"api_key": key, "type": "movie" if kind == "movie" else "tv", "languages": lang,
              "unpack": 1, "hi": 1, "releases": 1, "comment": 1, "subs_per_page": 30, "client": "custom_integration"}
    params.update(base)
    params.update(extra)
    time.sleep(PAUSE)
    try:
        r = requests.get(API, params=params, timeout=20)
    except requests.RequestException:
        _run["errors"] += 1
        if _run["errors"] >= 3 or manual:
            raise Stop(E("msg.subdl_sem_conexo_com_o_subdl"))
        return None
    _run["errors"] = 0
    if r.status_code == 429:
        _block()
        raise Stop(E("msg.subdl_limite_dirio_de_buscas_do_su"))
    if r.status_code in (401, 403):
        raise Stop(E("msg.subdl_o_subdl_recusou_a_chave"))
    try:
        j = r.json()
    except ValueError:
        return None
    if r.status_code != 200 or not isinstance(j, dict):
        return None
    if j.get("status") is False:
        err = str(j.get("error") or "").lower()
        if "api" in err and "key" in err:
            raise Stop(E("msg.subdl_o_subdl_recusou_a_chave"))
        if "limit" in err or "quota" in err:
            _block()
            raise Stop(E("msg.subdl_limite_do_subdl"))
        return [], []  # "não achei esse título"
    res = [x for x in (j.get("results") or []) if isinstance(x, dict)]
    return res, [x for x in (j.get("subtitles") or []) if isinstance(x, dict)]


def _match(results, it):
    """Posição, em `results`, do título que é o do item (pelo id TMDB/IMDb; sem ids, pelo nome e ano)."""
    imdb = (it.get("imdb") or "").lower()
    for i, r in enumerate(results):
        if (_int(r.get("tmdb_id")) and _int(r.get("tmdb_id")) == it["tmdb"]) or (imdb and str(r.get("imdb_id") or "").lower() == imdb):
            return i
    names = {_norm(it.get("title")), _norm(it.get("original_title"))} - {""}
    for i, r in enumerate(results):
        if r.get("tmdb_id") or r.get("imdb_id"):
            continue  # tem id e não é o do item
        if _norm(r.get("name")) not in names:
            continue
        if it["kind"] == "movie" and _int(r.get("year")) and it.get("year") and abs(_int(r["year"]) - int(it["year"])) > 1:
            continue
        return i
    return None


def bases(it):
    """Consultas por ordem de confiança, sempre a partir do item já identificado: id TMDB, id IMDb e o nome (original e atual)."""
    out = [({"tmdb_id": it["tmdb"]}, f"tmdb {it['tmdb']}")]
    if it.get("imdb"):
        out.append(({"imdb_id": it["imdb"]}, f"imdb {it['imdb']}"))
    seen = set()
    for n in (it.get("original_title"), it.get("title")):
        if n and n.lower() not in seen:
            seen.add(n.lower())
            d = {"film_name": n}
            if it["kind"] == "movie" and it.get("year"):
                d["year"] = it["year"]
            out.append((d, f"nome {n!r}"))
    return out


def _search(key, lang, it, base, variant, manual=False):
    """Legendas do título do item por uma consulta (`variant`: 'ep' = temporada+episódio; 'season' = pacotes da temporada).
    Devolve (subs, conhecido): subs None = falha passageira, [] = nada; conhecido = o SubDL reconhece o título (devolveu `results`)."""
    extra = {}
    if it["kind"] == "episode":
        extra = {"season_number": it["season"], "episode_number": it["episode"]} if variant == "ep" else {"season_number": it["season"], "full_season": 1}
    got = _call(key, lang, it["kind"], base, extra, manual)
    if got is None:
        return None, False
    results, subs = got
    known = bool(results)
    if "film_name" in base:  # busca por nome: confere se o título devolvido é o do item
        i = _match(results, it)
        if i is None:
            return [], False
        if i > 0:  # o título certo não é o 1º: busca de novo por ele
            sd = results[i].get("sd_id")
            if not sd:
                return [], False
            got = _call(key, lang, it["kind"], {"sd_id": sd}, extra, manual)
            if got is None:
                return None, False
            subs = got[1]
    return subs, known


def find(key, lang, it, video_base, manual=False):
    """(subs, consultas tentadas): tenta as consultas até uma devolver legenda utilizável. subs None = falha passageira."""
    plan = bases(it)
    hint = _run["hint"].get(it["tmdb"])
    if hint is not None and hint < len(plan):
        plan.insert(0, plan.pop(hint))  # a consulta que deu certo para esta série/filme vai primeiro
    variants = ("ep",) if it["kind"] == "movie" else ("ep", "season")
    tried = []
    for base, label in plan:
        known = False
        for v in variants:
            subs, k = _search(key, lang, it, base, v, manual)
            known = known or k
            tried.append(label + ("" if v == "ep" else " (temporada)"))
            if subs is None:
                return None, tried
            if candidates(subs, it["kind"], it["season"], it["episode"], video_base):
                _run["hint"][it["tmdb"]] = bases(it).index((base, label))
                return subs, tried
        if known and ("tmdb_id" in base or "imdb_id" in base):
            break  # o SubDL conhece o título e não tem legenda neste idioma: imdb/nome só gastariam busca à toa
    return [], tried


def name_base(it):
    """Texto de referência para ordenar candidatas e escolher o arquivo do .zip: o título do filme/série (atual e original),
    o ano ou SxxExx. Nunca o nome do arquivo de vídeo, que muitas vezes nada tem a ver com o título."""
    parts = [it.get("title"), it.get("original_title")]
    if it.get("kind") == "episode" and it.get("season") and it.get("episode"):
        parts.append(f"S{int(it['season']):02d}E{int(it['episode']):02d}")
    elif it.get("year"):
        parts.append(str(it["year"]))
    return " ".join(str(p) for p in parts if p)


def _ep_of(text):
    m = _SXE.search(text or "")
    return (int(m.group(1) or m.group(3)), int(m.group(2) or m.group(4))) if m else None


def candidates(subs, kind, season, episode, video_base):
    """Lista ordenada (melhor primeiro) de {url, forced, score, pack}. O texto de referência (`name_base`: título e ano/SxxExx, não o nome do arquivo) só ordena as candidatas, nunca as exclui;
    para episódio, só entram legendas do episódio (campos do SubDL ou SxxExx no nome) e pacotes que possam conter o episódio."""
    want = _tokens(video_base)
    out = []
    for s in subs:
        names = " ".join(str(s.get(k) or "") for k in ("release_name", "name", "comment"))
        s_forced = bool(_FORCED.search(names))
        pack = bool(s.get("full_season"))
        files = s.get("unpack_files") if isinstance(s.get("unpack_files"), list) else []
        if kind == "episode":
            ss, se = _int(s.get("season")), _int(s.get("episode"))
            lo, hi_ = _int(s.get("episode_from")), _int(s.get("episode_end"))
            if pack and ss and ss != season:
                continue
            if pack and lo and hi_ and not lo <= episode <= hi_ and not files:
                continue
        if files:
            for f in files:
                if not isinstance(f, dict) or str(f.get("format") or "").lower() not in ("srt", "subrip") or not f.get("url"):
                    continue
                fname = " ".join(str(f.get(k) or "") for k in ("name", "release_name"))
                if kind == "episode":
                    fs, fe = _int(f.get("season")), _int(f.get("episode"))
                    got = (fs, fe) if fs and fe else _ep_of(fname)
                    if got != (season, episode):
                        continue  # outro episódio do pacote (ou sem como saber qual é)
                hi = bool(f.get("hi"))
                score = len(want & _tokens(fname + " " + names)) * 10 + (0 if hi else 5) + 3
                out.append({"url": DL + f["url"], "forced": s_forced or bool(_FORCED.search(fname)), "score": score, "pack": False, "zip": False,
                            "release": str(f.get("release_name") or f.get("name") or s.get("release_name") or s.get("name") or ""), "author": str(s.get("author") or ""),
                            "hi": hi, "downloads": _int(s.get("downloads"))})
        elif s.get("url"):
            if kind == "episode" and not pack:
                got = (ss, se) if ss and se else _ep_of(names)
                if got != (season, episode):
                    continue  # sem numeração do episódio não dá para saber de qual é
            hi = bool(s.get("hi"))
            score = len(want & _tokens(names)) * 10 + (0 if hi else 5) + (0 if pack else 3)
            out.append({"url": DL + s["url"], "forced": s_forced, "score": score, "pack": pack, "zip": True,
                        "release": str(s.get("release_name") or s.get("name") or ""), "author": str(s.get("author") or ""),
                        "hi": hi, "downloads": _int(s.get("downloads"))})
    out.sort(key=lambda c: -c["score"])
    return out


def _download(url, manual=False):
    if not manual and _run["download"] >= MAX_DOWNLOAD:
        raise Stop(E("msg.subdl_limite_de_downloads_por_exam"))
    if not manual:
        _run["download"] += 1
    time.sleep(PAUSE)
    try:
        r = requests.get(url, timeout=30, stream=True, headers={"User-Agent": "StarFlix"})
        if r.status_code == 429:
            raise Stop(E("msg.subdl_limite_dirio_de_downloads_do"))
        if r.status_code != 200:
            return None
        data = b""
        for chunk in r.iter_content(65536):
            data += chunk
            if len(data) > MAX_ZIP:
                break
    except requests.RequestException:
        return None
    return data if 0 < len(data) <= MAX_ZIP else None


def _decode(raw):
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def extract_srt(data, kind, season, episode, video_base):
    """Texto do .srt: o próprio arquivo ou, se for .zip, o arquivo certo de dentro (episódio / melhor nome). None se não houver."""
    if data[:2] != b"PK":
        raw = data
    else:
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            return None
        names = [i for i in z.infolist() if not i.is_dir() and i.filename.lower().endswith(".srt")
                 and "__macosx" not in i.filename.lower() and 0 < i.file_size <= MAX_SRT]
        if kind == "episode":
            def ep_of(n):
                return _ep_of(os.path.basename(n))
            exact = [i for i in names if ep_of(i.filename) == (season, episode)]
            if exact:
                names = exact
            elif len(names) == 1 and ep_of(names[0].filename) is None:
                pass  # zip de um arquivo só, sem numeração no nome: é o do episódio
            else:
                names = []
        if not names:
            return None
        want = _tokens(video_base)
        names.sort(key=lambda i: (-len(want & _tokens(i.filename)), -i.file_size))
        try:
            raw = z.read(names[0])
        except (zipfile.BadZipFile, RuntimeError, OSError):
            return None
    text = _decode(raw)
    return text if "-->" in text and len(text) > 50 else None


def save(video_path, token, forced, text, overwrite=False):
    """Grava ao lado do vídeo; devolve o caminho (ou None se a pasta não aceitar escrita)."""
    out = f"{os.path.splitext(video_path)[0]}.{token}{'.forced' if forced else ''}.srt"
    if os.path.exists(out) and not overwrite:
        return out
    tmp = out + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text.lstrip("\ufeff"))
        os.replace(tmp, out)
    except OSError:
        log.warning("legenda: sem permissão para gravar %s", out)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return None
    return out


# ---------------------------------------------------------------- por item e por biblioteca

def _due(conn, path, kind):
    row = conn.execute("SELECT at FROM subtitle_fetch WHERE path = ? AND kind = ?", (path, kind)).fetchone()
    if not row:
        return True
    return _run["manual"] and row["at"] < _run["start"] and row["at"] < time.time() - RETRY_DAYS * 86400


def _mark(conn, path, kind, status):
    conn.execute("INSERT INTO subtitle_fetch (path, kind, status, at) VALUES (?, ?, ?, ?) "
                 "ON CONFLICT(path, kind) DO UPDATE SET status = excluded.status, at = excluded.at", (path, kind, status, int(time.time())))


def _items(conn, library_id, media_id):
    items, seen = [], set()
    for r in conn.execute("SELECT path, tmdb_id, info, title, original_title, year, imdb_id FROM media WHERE library_id = ? AND path IS NOT NULL "
                          "AND tmdb_id > 0 AND (? IS NULL OR id = ?) ORDER BY id", (library_id, media_id, media_id)):
        items.append({"kind": "movie", "path": r["path"], "tmdb": r["tmdb_id"], "season": None, "episode": None, "info": r["info"],
                      "title": r["title"], "original_title": r["original_title"], "year": r["year"], "imdb": r["imdb_id"]})
    for r in conn.execute("SELECT e.path, e.season, e.episode, e.info, m.tmdb_id, m.title, m.original_title, m.year, m.imdb_id FROM episodes e "
                          "JOIN media m ON m.id = e.media_id WHERE m.library_id = ? AND m.tmdb_id > 0 AND (? IS NULL OR m.id = ?) "
                          "ORDER BY m.id, e.season, e.episode", (library_id, media_id, media_id)):
        if r["path"] in seen:
            continue  # arquivo de vários episódios: uma legenda só (a do 1º)
        seen.add(r["path"])
        items.append({"kind": "episode", "path": r["path"], "tmdb": r["tmdb_id"], "season": r["season"], "episode": r["episode"], "info": r["info"],
                      "title": r["title"], "original_title": r["original_title"], "year": r["year"], "imdb": r["imdb_id"]})
    return items


def _fetch_kind(it, subs, want_forced, token, base_name):
    """Baixa e grava a legenda (completa ou forçada). 'ok' | 'none'."""
    cands = [c for c in candidates(subs, it["kind"], it["season"], it["episode"], base_name) if c["forced"] == want_forced]
    for c in cands[:TRIES]:
        data = _download(c["url"])
        if not data:
            continue
        text = extract_srt(data, it["kind"], it["season"], it["episode"], base_name)
        if text and save(it["path"], token, want_forced, text):
            return "ok"
    return "none"


def fetch_subtitles(library_id, media_id=None):
    """Etapa do exame: baixa as legendas que faltam dos itens identificados (media_id restringe a um item). Devolve quantas gravou.
    A busca e a escolha da candidata partem do item já identificado (id TMDB/IMDb e título atual/original), não do nome do arquivo."""
    key, lang = config.SUBDL_API_KEY, config.SUBDL_LANG
    _roll_day()
    if not key or lang not in LANGS or _run["stop"] or _day["blocked"] or _day["n"] >= DAILY_MAX:
        return 0
    token, base = LANGS[lang]
    saved = 0
    with get_db() as conn:
        items = _items(conn, library_id, media_id)
    for it in items:
        if _run["stop"]:
            break
        path = it["path"]
        if not os.path.isfile(path):
            continue
        have_full, have_forced = have(path, it["info"], base)
        with get_db() as conn:
            todo = []
            if not have_full and _due(conn, path, "full"):
                todo.append("full")
            if not have_forced and audio_in(it["info"], base) and _due(conn, path, "forced"):
                todo.append("forced")
        if not todo:
            continue
        if scanstate.cancelled(library_id):
            raise scanstate.ScanCancelled()  # biblioteca apagada durante o exame
        base_name = name_base(it)
        label = it["title"] + (f" S{it['season']:02d}E{it['episode']:02d}" if it["kind"] == "episode" else "")
        try:
            subs, tried = find(key, lang, it, base_name)
            if subs is None:
                continue  # falha passageira: sem marcar, tenta no próximo exame
            with get_db() as conn:
                for k in todo:
                    status = _fetch_kind(it, subs, k == "forced", token, base_name)
                    _mark(conn, path, k, status)
                    saved += status == "ok"
                    if status == "none":
                        log.info("legenda %s (%s) de %s: nada encontrado no SubDL (consultas: %s)", k, lang, label, "; ".join(tried))
        except Stop as e:
            _run["stop"] = str(e)
            log.warning("legendas (SubDL): %s; as que faltam ficam para o próximo exame", e)
    return saved


# ---------------------------------------------------------------- busca manual no player (47.3)
LANG_LABELS = {"BR_PT": "lang.pt_br", "PT": "lang.pt_pt", "EN": "lang.en", "ES": "lang.es",
               "FR": "lang.fr", "DE": "lang.de", "IT": "lang.it", "JA": "lang.ja",
               "RU": "lang.ru", "ZH": "lang.zh", "TR": "lang.tr"}  # chaves; traduzidas em subtitles.subs_search
CACHE_TTL = 24 * 3600
MAX_SHOWN = 40
_cache = {}  # (tipo, id, idioma) -> {"at", "cands", "tried"}; evita gastar cota ao reabrir a janela


def budget():
    _roll_day()
    return {"used": _day["n"], "max": DAILY_MAX, "blocked": _day["blocked"]}


def item_dict(kind, item_id):
    """O item identificado (mesmo formato de `_items`); None se não houver correspondência ou arquivo."""
    with get_db() as conn:
        if kind == "movie":
            r = conn.execute("SELECT path, tmdb_id, info, title, original_title, year, imdb_id FROM media WHERE id = ?", (item_id,)).fetchone()
            if not r or not r["path"] or (r["tmdb_id"] or 0) <= 0:
                return None
            return {"kind": "movie", "path": r["path"], "tmdb": r["tmdb_id"], "season": None, "episode": None, "info": r["info"],
                    "title": r["title"], "original_title": r["original_title"], "year": r["year"], "imdb": r["imdb_id"]}
        r = conn.execute("SELECT e.path, e.season, e.episode, e.info, m.tmdb_id, m.title, m.original_title, m.year, m.imdb_id FROM episodes e "
                         "JOIN media m ON m.id = e.media_id WHERE e.id = ?", (item_id,)).fetchone()
        if not r or not r["path"] or (r["tmdb_id"] or 0) <= 0:
            return None
        return {"kind": "episode", "path": r["path"], "tmdb": r["tmdb_id"], "season": r["season"], "episode": r["episode"], "info": r["info"],
                "title": r["title"], "original_title": r["original_title"], "year": r["year"], "imdb": r["imdb_id"]}


def search_manual(kind, item_id, lang, refresh=False):
    """Candidatas do SubDL para o item no idioma `lang` (chave de LANGS). Levanta ValueError (mensagem pt-BR) ou Stop."""
    if not config.SUBDL_API_KEY:
        raise ValueError(E("msg.configure_chave_subdl_configuracoes_agentes"))
    if lang not in LANGS:
        raise ValueError(E("err.idioma_invalido"))
    it = item_dict(kind, item_id)
    if not it:
        raise ValueError(E("err.item_sem_correspondencia_corrija_correspondencia"))
    ck = (kind, item_id, lang)
    hit = _cache.get(ck)
    if hit and not refresh and time.time() - hit["at"] < CACHE_TTL:
        return hit["cands"], hit["tried"], True
    base_name = name_base(it)
    subs, tried = find(config.SUBDL_API_KEY, lang, it, base_name, manual=True)
    if subs is None:
        raise ValueError(E("err.nao_foi_possivel_consultar_subdl"))
    cands = candidates(subs, it["kind"], it["season"], it["episode"], base_name)[:MAX_SHOWN]
    for i, c in enumerate(cands):
        c["id"] = i
    _cache[ck] = {"at": time.time(), "cands": cands, "tried": tried}
    return cands, tried, False


def pick_manual(kind, item_id, lang, cand_id):
    """Baixa a candidata escolhida e grava ao lado do vídeo (substitui a que já existe). Devolve o nome do arquivo gravado."""
    hit = _cache.get((kind, item_id, lang))
    if not hit or not isinstance(cand_id, int) or isinstance(cand_id, bool) or not 0 <= cand_id < len(hit["cands"]):
        raise ValueError(E("msg.resultado_expirado_busque_novo"))
    it = item_dict(kind, item_id)
    if not it or not os.path.isfile(it["path"]):
        raise ValueError(E("err.arquivo_item_nao_encontrado"))
    c = hit["cands"][cand_id]
    base_name = name_base(it)
    data = _download(c["url"], manual=True)
    text = extract_srt(data, it["kind"], it["season"], it["episode"], base_name) if data else None
    if not text:
        raise ValueError(E("err.nao_foi_possivel_baixar_esta"))
    out = save(it["path"], LANGS[lang][0], c["forced"], text, overwrite=True)
    if not out:
        raise ValueError(E("err.sem_permissao_gravar_pasta_video"))
    with get_db() as conn:
        _mark(conn, it["path"], "forced" if c["forced"] else "full", "ok")
    return os.path.basename(out)


def removable(video_path, filename):
    """True se `filename` é uma legenda que o SubDL gravaria ao lado deste vídeo (`<nome>.<idioma>[.forced].srt`)."""
    base = os.path.splitext(os.path.basename(video_path))[0]
    for tok, _ in LANGS.values():
        for f in ("", ".forced"):
            if filename == f"{base}.{tok}{f}.srt":
                return True
    return False


def remove_manual(kind, item_id, filename):
    it = item_dict(kind, item_id)
    path = it["path"] if it else None
    if not path:  # item sem correspondência: ainda dá para remover o que foi baixado antes
        from server.stream import get_item
        path = get_item(kind, item_id)[0]
    if not isinstance(filename, str) or not removable(path, filename):
        raise ValueError(E("err.so_remover_legendas_baixadas_pelo"))
    full = os.path.join(os.path.dirname(path), filename)
    try:
        os.remove(full)
    except FileNotFoundError:
        raise ValueError(E("err.legenda_nao_encontrada"))
    except OSError:
        raise ValueError(E("err.sem_permissao_apagar_arquivo"))
    with get_db() as conn:  # a busca automática não baixa de novo o que o admin removeu
        for k in ("full", "forced"):
            _mark(conn, path, k, "removed")
