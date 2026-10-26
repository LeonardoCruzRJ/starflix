import contextlib
import logging
import os
import re
import threading
import time

import config
from server.i18n import t as t_, tr
from server.db import get_db, library_folders, lib_prefs, prune_stars
from server.metadata import apply_local_art, download_images, download_posters, identify_episodes, identify_seasons, prune_people, remove_local, show_image_names, identify_movies, identify_shows
from server import markers, scanstate, trickplay
from server.dedupe import merge_movies, merge_shows
from server.probe import probe_library
from server.subdl import begin_run as subdl_begin_run, fetch_subtitles

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".wmv", ".ts", ".flv", ".mpg", ".mpeg"}

_YEAR_BR = re.compile(r"[\(\[]\s*((?:19|20)\d{2})\s*[\)\]]")
_YEAR_TK = re.compile(r"(?<=[\s._\-])((?:19|20)\d{2})(?=[\s._\-\)\]]|$)")


_TAGS = re.compile(
    r"(?<![A-Za-z0-9])(?:2160p|1080[pi]|720p|576p|480p|blu-?ray|bdrip|brrip|bdremux|web-?dl|web-?rip|hdtv|dvdrip|hdrip"
    r"|x26[45]|h\.?26[45]|hevc|xvid|divx|uhd|remux|4k|hdr10|hdr|dv|imax|proper|repack|amzn|nf)(?![A-Za-z0-9])", re.I)


def _parse(name):
    """(título, ano): prefere o último ano entre parênteses/colchetes; sem eles, o último ano solto.
    Tags de release (1080p, BluRay, x264...) cortam o título quando algo vem antes delas."""
    max_year = time.localtime().tm_year + 1  # "Blade Runner 2049" não é ano de lançamento
    ms = [m for m in _YEAR_BR.finditer(name) if int(m.group(1)) <= max_year]
    if not ms:
        ms = [m for m in _YEAR_TK.finditer(name) if int(m.group(1)) <= max_year and re.search(r"\w", name[: m.start()])]
    m = ms[-1] if ms else None
    title, year = (name[: m.start()], int(m.group(1))) if m else (name, None)
    t = _TAGS.search(title)
    if t and re.search(r"\w", title[: t.start()]):
        title = title[: t.start()]
    title = re.sub(r"[\s._\-\(\[]+$", "", title)
    title = re.sub(r"[\s._]+", " ", title).strip()
    return title, year


def parse_movie_name(path):
    """Extrai (título, ano) do arquivo; se não houver ano, tenta a pasta pai."""
    title, year = _parse(os.path.splitext(os.path.basename(path))[0])
    if year is None:
        parent = os.path.basename(os.path.dirname(path))
        _, pyear = _parse(parent)
        if pyear:
            year = pyear
    return title or os.path.basename(path), year


SKIP_DIRS = {  # extras do padrão Plex/Kodi: não são filmes nem episódios
    "extras", "featurettes", "sample", "samples", "trailers", "behind the scenes", "deleted scenes",
    "interviews", "scenes", "shorts", "other",
}
SKIP_FILE = re.compile(r"(^|[\W_])(sample|trailer)$", re.I)  # só como sufixo: "Filme-trailer", "x.sample"; "Trailer Park Boys" passa


def video_files(root, plain=False):
    """`plain=True` (biblioteca Outros Vídeos): não pula pastas de extras nem arquivos sample/trailer."""
    seen = set()  # realpath já visitado: symlinks são seguidos sem entrar em loop
    for dirpath, dirnames, files in os.walk(root, followlinks=True):
        real = os.path.realpath(dirpath)
        if real in seen:
            dirnames[:] = []
            continue
        seen.add(real)
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and (plain or d.lower() not in SKIP_DIRS))
        for f in sorted(files):
            name, ext = os.path.splitext(f)
            if not f.startswith(".") and ext.lower() in VIDEO_EXTS and (plain or not SKIP_FILE.search(name)):
                yield os.path.join(dirpath, f)


def _roots(conn, library_id):
    """Pastas da biblioteca que existem no servidor (28.2)."""
    return [p for p in library_folders(conn, library_id) if os.path.isdir(p)]


def _root_of(path, roots):
    for r in roots:
        if path == r or path.startswith(r.rstrip(os.sep) + os.sep):
            return r
    return None


def scan_movies(library_id):
    """Adiciona ao banco os filmes novos da biblioteca. Retorna quantos foram adicionados."""
    added = 0
    with get_db() as conn:
        lib = conn.execute("SELECT * FROM libraries WHERE id = ? AND type = 'movie'", (library_id,)).fetchone()
        roots = _roots(conn, library_id) if lib else []
        if not roots:
            return 0
        known = {r["path"] for r in conn.execute("SELECT path FROM media WHERE library_id = ?", (library_id,))}
        known |= {r["path"] for r in conn.execute("SELECT d.path FROM media_dups d JOIN media m ON m.id = d.media_id "
                                                  "WHERE m.library_id = ?", (library_id,))}  # 35.3: arquivos repetidos já unidos
        for root in roots:
            for path in video_files(root):
                if path in known:
                    continue
                title, year = parse_movie_name(path)
                conn.execute(
                    "INSERT INTO media (library_id, title, year, path) VALUES (?, ?, ?, ?)",
                    (library_id, title, year, path),
                )
                conn.commit()
                added += 1
    return added


def scan_videos(library_id):
    """34.2: biblioteca Outros Vídeos — um item por arquivo (subpastas incluídas), título = nome do arquivo sem extensão.
    Sem ano, sem TMDB/TVDB. Retorna quantos foram adicionados."""
    added = 0
    with get_db() as conn:
        lib = conn.execute("SELECT * FROM libraries WHERE id = ? AND type = 'video'", (library_id,)).fetchone()
        roots = _roots(conn, library_id) if lib else []
        if not roots:
            return 0
        known = {r["path"] for r in conn.execute("SELECT path FROM media WHERE library_id = ?", (library_id,))}
        for root in roots:
            for path in video_files(root, plain=True):
                if path in known:
                    continue
                conn.execute(
                    "INSERT INTO media (library_id, title, path) VALUES (?, ?, ?)",
                    (library_id, os.path.splitext(os.path.basename(path))[0], path),
                )
                conn.commit()
                known.add(path)
                added += 1
    return added


_SXE = re.compile(r"[sS](\d{1,2})[\s._-]*[eE](\d{1,3})")
_NXN = re.compile(r"(?<!\d)(\d{1,2})[xX](\d{2,3})(?!\d)")


_SEASON_DIR = re.compile(r"^(?:(?:season|temporada|saison|staffel|s)[\s._-]*\d{1,2}|specials?|especiais)$", re.I)
_EXTRA_EP = re.compile(r"(-)?[\s._]*[eE](\d{1,3})")
_RANGE_EP = re.compile(r"-(\d{1,3})(?![0-9A-Za-z])")  # "S01E01-02" (intervalo do Sonarr); "-720p" e "-10bit" não casam


def _episode_numbers(stem, m):
    """Episódios do arquivo: o primeiro e os seguintes (`S01E01E02`, `S01E01-E02`; com hífen preenche o intervalo)."""
    eps = [int(m.group(2))]
    pos = m.end()
    while True:
        x = _EXTRA_EP.match(stem, pos)
        if x:
            n = int(x.group(2))
            if n <= eps[-1]:
                return eps
            eps += list(range(eps[-1] + 1, n + 1)) if x.group(1) and n - eps[-1] <= 20 else [n]
            pos = x.end()
            continue
        r = _RANGE_EP.match(stem, pos)
        if not r or not eps[-1] < int(r.group(1)) <= eps[-1] + 20:
            return eps
        eps += list(range(eps[-1] + 1, int(r.group(1)) + 1))
        pos = r.end()


def parse_episodes(root, path):
    """Retorna (série, ano, temporada, [episódios]) ou None se não identificar."""
    stem = os.path.splitext(os.path.basename(path))[0]
    sxe = _SXE.search(stem)
    m = sxe or _NXN.search(stem)
    if not m:
        return None
    season = int(m.group(1))
    eps = _episode_numbers(stem, m) if sxe else [int(m.group(2))]
    rel = os.path.relpath(path, root).split(os.sep)
    source = rel[0] if len(rel) > 1 and not _SEASON_DIR.match(rel[0]) else stem[: m.start()]
    title, year = _parse(source)
    if not title and len(rel) > 1:  # biblioteca aponta para a pasta da série ("Season 1/S01E01.mkv"): usa o nome da pasta
        title, year = _parse(os.path.basename(os.path.abspath(root)))
    if not title:
        return None
    return title, year, season, eps


def parse_episode(root, path):
    """Retorna (série, ano, temporada, episódio) ou None se não identificar (1º episódio do arquivo)."""
    r = parse_episodes(root, path)
    return (r[0], r[1], r[2], r[3][0]) if r else None


def _show_walk(conn, mid, roots):
    """46.4: (raiz, pasta) a percorrer para achar episódios novos de UMA série: a pasta da série de cada episódio já conhecido."""
    out = []
    for r in conn.execute("SELECT path FROM episodes WHERE media_id = ?", (mid,)):
        root = _root_of(r["path"], roots)
        if not root:
            continue
        rel = os.path.relpath(r["path"], root).split(os.sep)
        top = os.path.join(root, rel[0]) if len(rel) > 1 and not _SEASON_DIR.match(rel[0]) else root
        if (root, top) not in out:
            out.append((root, top))
    return out


def scan_shows(library_id, only=None):
    """Adiciona séries e episódios novos da biblioteca. Retorna episódios adicionados.
    46.4: `only` (id da série) percorre só a pasta dessa série e só acrescenta episódios a ela (não cria séries)."""
    added = 0
    with get_db() as conn:
        lib = conn.execute("SELECT * FROM libraries WHERE id = ? AND type = 'show'", (library_id,)).fetchone()
        roots = _roots(conn, library_id) if lib else []
        if not roots:
            return 0
        known, have, shows, by_title = {}, set(), {}, {}
        for r in conn.execute(
            "SELECT e.path, e.media_id, e.season, e.episode FROM episodes e JOIN media m ON m.id = e.media_id "
            "WHERE m.library_id = ?",
            (library_id,),
        ):
            known[r["path"]] = r["media_id"]
            have.add((r["media_id"], r["season"], r["episode"]))
            parsed = parse_episode(_root_of(r["path"], roots) or roots[0], r["path"])  # chave (título, ano) da pasta; o TMDB pode mudar media.year
            if parsed:
                shows.setdefault((parsed[0].lower(), parsed[1]), r["media_id"])
                by_title.setdefault(parsed[0].lower(), set()).add(r["media_id"])
        for r in conn.execute("SELECT d.path, d.media_id FROM media_dups d JOIN media m ON m.id = d.media_id "
                              "WHERE m.library_id = ?", (library_id,)):  # 35.4: arquivo repetido de episódio aponta para a série que ficou
            parsed = parse_episode(_root_of(r["path"], roots) or roots[0], r["path"])
            if parsed:
                shows.setdefault((parsed[0].lower(), parsed[1]), r["media_id"])
                by_title.setdefault(parsed[0].lower(), set()).add(r["media_id"])
        walk = [(r, r) for r in roots] if not only else _show_walk(conn, only, roots)
        for root, top in walk:
            for path in video_files(top):
                info = parse_episodes(root, path)
                if not info:
                    continue
                title, year, season, episodes = info
                if path in known:
                    if len(episodes) == 1:
                        continue
                    mid = known[path]  # arquivo de vários episódios: completa os que faltam
                else:
                    tl = title.lower()
                    mid = shows.get((tl, year))
                    if mid is None and year is None and len(by_title.get(tl, ())) == 1:
                        mid = next(iter(by_title[tl]))  # sem ano na pasta: usa a única série com esse título
                    if mid is None and only:
                        continue  # 46.4: exame de uma série não cria outras
                    if mid is None:
                        mid = conn.execute(
                            "INSERT INTO media (library_id, title, year) VALUES (?, ?, ?)", (library_id, title, year)
                        ).lastrowid
                        shows[(tl, year)] = mid
                        by_title.setdefault(tl, set()).add(mid)
                if only and mid != only:
                    continue
                for episode in episodes:
                    if (mid, season, episode) in have:
                        continue  # duplicata (ex.: 1080p e 720p): mantém o primeiro arquivo
                    have.add((mid, season, episode))
                    conn.execute(
                        "INSERT INTO episodes (media_id, season, episode, path) VALUES (?, ?, ?, ?)",
                        (mid, season, episode, path),
                    )
                    added += 1
                conn.commit()
    return added


def _remove_poster(name):
    """Apaga o arquivo local da imagem (nomes que começam com '/' são caminhos remotos do TMDB)."""
    remove_local(name)


def prune_missing(library_id, only=None):
    """Remove do banco filmes/episódios cujo arquivo sumiu. Não faz nada se a pasta não existe ou está vazia (disco não montado).
    46.4: `only` (id do filme/série) limita a verificação a esse item."""
    removed = 0
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM libraries WHERE id = ?", (library_id,)).fetchone():
            return 0
        folders = library_folders(conn, library_id)
        ok = {f for f in folders if os.path.isdir(f) and next(video_files(f), None) is not None}
        if not ok:  # nenhuma pasta disponível (disco não montado): não apaga nada
            return 0

        def gone(path):  # arquivo sumiu; itens de pasta indisponível (9.5, por pasta) ficam
            if os.path.exists(path):
                return False
            root = _root_of(path, folders)
            return root is None or root in ok

        rows = conn.execute(
            "SELECT id, path, poster, backdrop, logo, square FROM media WHERE library_id = ? AND path IS NOT NULL AND (? IS NULL OR id = ?)",
            (library_id, only, only)
        ).fetchall()
        for r in rows:
            if gone(r["path"]):
                conn.execute("DELETE FROM media WHERE id = ?", (r["id"],))
                conn.commit()
                for k in ("poster", "backdrop", "logo", "square"):
                    _remove_poster(r[k])
                removed += 1
        rows = conn.execute(
            "SELECT e.id, e.path, e.still FROM episodes e JOIN media m ON m.id = e.media_id WHERE m.library_id = ? AND (? IS NULL OR m.id = ?)",
            (library_id, only, only),
        ).fetchall()
        for r in rows:
            if gone(r["path"]):
                conn.execute("DELETE FROM episodes WHERE id = ?", (r["id"],))
                conn.commit()
                _remove_poster(r["still"])
                removed += 1
        orphans = conn.execute(
            "SELECT id, poster, backdrop, logo, square FROM media WHERE library_id = ? AND path IS NULL "
            "AND id NOT IN (SELECT media_id FROM episodes) AND (? IS NULL OR id = ?)",
            (library_id, only, only),
        ).fetchall()
        for o in orphans:
            for n in show_image_names(conn, "m.id = ?", (o["id"],)):
                _remove_poster(n)
            conn.execute("DELETE FROM media WHERE id = ?", (o["id"],))
            for k in ("poster", "backdrop", "logo", "square"):
                _remove_poster(o[k])
        conn.execute("DELETE FROM progress WHERE item_type = 'movie' AND item_id NOT IN (SELECT id FROM media)")
        conn.execute("DELETE FROM progress WHERE item_type = 'episode' AND item_id NOT IN (SELECT id FROM episodes)")
        prune_stars(conn)
        trickplay.prune()  # 49.1
        try:
            from server import optimize  # import tardio (52.9): apaga as versões otimizadas de itens removidos
            optimize.prune()
        except Exception:
            pass
    prune_people()
    return removed


log = logging.getLogger("starflix.scan")
if not log.handlers:  # 35.1: o exame escreve cada etapa no journal (sem depender da config de logging)
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s starflix.scan: %(message)s"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)
    log.propagate = False

_progress = {}


def progress():
    """Etapa em andamento do exame: {'lib', 'stage', 'since'} (vazio fora do exame)."""
    d = dict(_progress)
    if d.get("stage"):
        d["stage"] = tr(d["stage"])  # a etapa fica guardada como chave; o texto sai no idioma de quem pergunta
    return d


def _stage(library_id, name, fn):
    scanstate.clear()
    scanstate.set_lib(library_id)  # 35.22: biblioteca apagada no meio do exame -> ScanCancelled
    _progress.update(lib=library_id, stage=name, since=time.time())
    t = time.time()
    log.info("biblioteca %s: %s…", library_id, t_(name, "pt-BR"))
    try:
        return fn(library_id)
    finally:
        log.info("biblioteca %s: %s concluído em %.1f s", library_id, t_(name, "pt-BR"), time.time() - t)


def process_items(library_id):
    """35.21: item a item — analisa, identifica, aplica arte local e baixa pôster/imagens de UM item antes de passar ao próximo,
    então capa e dados aparecem na grade e na página do item assim que cada um termina (e não só no fim do exame).
    As etapas por biblioteca que vêm depois só varrem o que sobrou."""
    with get_db() as conn:
        lib = conn.execute("SELECT type, prefs FROM libraries WHERE id = ?", (library_id,)).fetchone()
        if not lib or lib["type"] not in ("movie", "show"):
            return 0
        movie = lib["type"] == "movie"
        if lib_prefs(lib)["agent"] == "none":  # agente Nenhum: sem identificação (a varredura por etapas cuida do resto)
            return 0
        if movie:
            sql = ("SELECT id FROM media WHERE library_id = ? AND path IS NOT NULL AND (tmdb_id IS NULL OR (tmdb_id > 0 AND meta_ok IS NULL) "
                   "OR info IS NULL) ORDER BY id")
        else:
            sql = ("SELECT id FROM media m WHERE library_id = ? AND path IS NULL AND (tmdb_id IS NULL OR (tmdb_id > 0 AND meta_ok IS NULL) "
                   "OR EXISTS (SELECT 1 FROM episodes e WHERE e.media_id = m.id AND e.info IS NULL)) ORDER BY id")
        ids = [r["id"] for r in conn.execute(sql, (library_id,))]
    done = 0
    for mid in ids:
        scanstate.set_current(mid)
        try:
            probe_library(library_id, mid)
            if movie:
                identify_movies(library_id, mid)
            else:
                identify_shows(library_id, mid)
                identify_episodes(library_id, mid)
                identify_seasons(library_id, mid)
            apply_local_art(library_id, mid)
            download_posters(library_id, mid)
            download_images(library_id, mid)
            fetch_subtitles(library_id, mid)  # 46.1: legenda do SubDL assim que o item termina de ser identificado
            done += 1
        except scanstate.ScanCancelled:
            raise
        except Exception:
            log.exception("falha ao processar o item %s da biblioteca %s", mid, library_id)
    return done


def scan_library(library_id):
    with get_db() as conn:
        lib = conn.execute("SELECT type FROM libraries WHERE id = ?", (library_id,)).fetchone()
    if not lib:
        return 0
    _stage(library_id, "scan.st.verificando_arquivos_ausentes", prune_missing)
    if lib["type"] == "video":  # 34.2: sem identificação, sem metadados, sem imagens (a miniatura é o frame, 34.3)
        added = _stage(library_id, "scan.st.procurando_videos", scan_videos)
        _stage(library_id, "scan.st.analisando_arquivos", probe_library)
        _stage(library_id, "scan.st.gerando_miniaturas", trickplay.generate_library)  # 49.2
        return added
    added = _stage(library_id, "scan.st.procurando_arquivos", scan_movies if lib["type"] == "movie" else scan_shows)
    _stage(library_id, "scan.st.processando_itens", process_items)
    _stage(library_id, "scan.st.analisando_arquivos", probe_library)
    if lib["type"] == "movie":
        _stage(library_id, "scan.st.identificando_filmes", identify_movies)
        _stage(library_id, "scan.st.unindo_filmes_duplicados", merge_movies)
    else:
        _stage(library_id, "scan.st.identificando_series", identify_shows)
        _stage(library_id, "scan.st.unindo_series_duplicadas", merge_shows)
        _stage(library_id, "scan.st.identificando_episodios", identify_episodes)
        _stage(library_id, "scan.st.identificando_temporadas", identify_seasons)
    _stage(library_id, "scan.st.aplicando_imagens_locais", apply_local_art)
    _stage(library_id, "scan.st.baixando_posteres", download_posters)
    _stage(library_id, "scan.st.baixando_imagens", download_images)
    _stage(library_id, "scan.st.baixando_legendas", fetch_subtitles)  # 46.1: o que sobrou (itens já identificados, "Examinar arquivos")
    if lib["type"] == "show":
        _stage(library_id, "scan.st.detectando_aberturas", markers.detect_markers)  # 48.5
    _stage(library_id, "scan.st.gerando_miniaturas", trickplay.generate_library)  # 49.2: por último, baixa prioridade
    return added


def examine_item(library_id, mid):
    """46.4: "Examinar arquivos" de UM filme/série (menu ⋮ da página do item): confere se os arquivos ainda existem, procura episódios
    novos na pasta da série e completa o que falta (análise, metadados, imagens, legendas). Quem já tem os dados não é tocado."""
    with get_db() as conn:
        lib = conn.execute("SELECT type FROM libraries WHERE id = ?", (library_id,)).fetchone()
    if not lib or lib["type"] not in ("movie", "show"):
        return
    movie = lib["type"] == "movie"
    scanstate.set_lib(library_id)
    prune_missing(library_id, mid)
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM media WHERE id = ?", (mid,)).fetchone():
            return  # o arquivo sumiu e o item saiu junto
    if not movie:
        scan_shows(library_id, mid)
    scanstate.set_current(mid)
    probe_library(library_id, mid)
    if movie:
        identify_movies(library_id, mid)
    else:
        identify_shows(library_id, mid)
        identify_episodes(library_id, mid)
        identify_seasons(library_id, mid)
    apply_local_art(library_id, mid)
    download_posters(library_id, mid)
    download_images(library_id, mid)
    fetch_subtitles(library_id, mid)
    if not movie:
        markers.detect_markers(library_id, mid)  # 48.5
    trickplay.generate_library(library_id, mid)  # 49.2


_lock = threading.Lock()


def is_scanning():
    return _lock.locked()


def cancel_library(library_id, wait=20):
    """35.22: biblioteca apagada — se o exame estiver nela (ou ainda for chegar nela), manda parar e espera sair dela."""
    if not _lock.locked():
        return
    scanstate.cancel(library_id)
    end = time.time() + wait
    while time.time() < end and _lock.locked() and _progress.get("lib") == library_id:
        time.sleep(0.2)


@contextlib.contextmanager
def exclusive():
    """Reserva a trava de exame (29.3); devolve False se já houver um exame rodando."""
    if not _lock.acquire(blocking=False):
        yield False
        return
    try:
        yield True
    finally:
        _lock.release()


_pending_lang = threading.Event()  # 59.37: troca de idioma pedida com um exame em andamento


def _reset_language():
    from server.metadata import reset_for_language
    with get_db() as conn:
        reset_for_language(conn)


def refresh_language_async():
    """59.37: nova varredura de metadados de todas as bibliotecas de filmes e séries no idioma ativo dos agentes (capa, sinopse,
    título, elenco, temporadas, episódios; campos travados ficam). Com um exame em andamento, começa assim que ele terminar."""
    if scan_async(None, before=_reset_language):
        return True
    _pending_lang.set()
    return False


def _run(library_id, before=None):
    try:
        if before:
            try:
                before()
            except Exception:
                logging.exception("falha ao preparar o exame da biblioteca %s", library_id)
        with get_db() as conn:
            ids = [library_id] if library_id else [r["id"] for r in conn.execute("SELECT id FROM libraries")]
        for i in ids:
            if scanstate.cancelled(i):
                scanstate.reset(i)
                continue
            try:
                scan_library(i)
                with get_db() as conn:  # 29.1: "Última atualização há …"
                    conn.execute("UPDATE libraries SET scanned_at = ? WHERE id = ?", (int(time.time()), i))
            except scanstate.ScanCancelled:
                log.info("biblioteca %s apagada durante o exame: exame encerrado", i)
            except Exception:
                log.exception("falha ao escanear a biblioteca %s", i)
            finally:
                scanstate.reset(i)
    finally:
        _progress.clear()
        scanstate.clear()
        scanstate.reset()
        _lock.release()
        if _pending_lang.is_set():  # 59.37: o idioma mudou durante este exame: refaz tudo no idioma novo
            _pending_lang.clear()
            refresh_language_async()


def scan_async(library_id=None, before=None, manual=False):
    """Escaneia em segundo plano (uma varredura por vez). Retorna False se já houver uma rodando.
    `before` roda dentro da trava, antes do exame (ex.: zerar meta_ok). `manual` = exame pedido pelo admin
    (46.1: as legendas que o SubDL não achou antes são tentadas de novo, uma vez neste exame)."""
    if not _lock.acquire(blocking=False):
        return False
    subdl_begin_run(manual)
    threading.Thread(target=_run, args=(library_id, before), daemon=True).start()
    return True


def _run_item(library_id, mid):
    t = time.time()
    _progress.update(lib=library_id, stage="Examinando o item", since=t)
    log.info("biblioteca %s: examinando o item %s…", library_id, mid)
    try:
        examine_item(library_id, mid)
    except scanstate.ScanCancelled:
        log.info("biblioteca %s apagada durante o exame do item %s", library_id, mid)
    except Exception:
        log.exception("falha ao examinar o item %s da biblioteca %s", mid, library_id)
    finally:
        log.info("biblioteca %s: exame do item %s concluído em %.1f s", library_id, mid, time.time() - t)
        _progress.clear()
        scanstate.clear()
        scanstate.manual_end(mid)  # a capa para de girar e a página do item recarrega
        scanstate.reset(library_id)
        _lock.release()


def examine_item_async(library_id, mid):
    """46.4: examina um item em segundo plano (mesma trava dos exames de biblioteca). Retorna False se já houver um exame rodando."""
    if not _lock.acquire(blocking=False):
        return False
    subdl_begin_run(True)  # como o "Examinar arquivos" da biblioteca: tenta de novo as legendas que faltam (respeitando RETRY_DAYS)
    scanstate.manual_start(mid)
    threading.Thread(target=_run_item, args=(library_id, mid), daemon=True).start()
    return True


def _run_trickplay(library_id, mid):
    try:
        if mid:
            scanstate.manual_start(mid)
        scanstate.set_lib(library_id)
        _progress.update(lib=library_id, stage="Gerando miniaturas", since=time.time())
        trickplay.generate_library(library_id, mid, force=True, budget=6 * 3600)
    except scanstate.ScanCancelled:
        pass
    except Exception:
        log.exception("falha ao gerar miniaturas (biblioteca %s)", library_id)
    finally:
        _progress.clear()
        scanstate.clear()
        if mid:
            scanstate.manual_end(mid)
        scanstate.reset(library_id)
        _lock.release()


def trickplay_async(library_id, mid=None):
    """49.2: \"Gerar miniaturas\" da biblioteca (ou de um filme/série) em segundo plano, com a trava dos exames; ignora a opção da biblioteca."""
    if not _lock.acquire(blocking=False):
        return False
    threading.Thread(target=_run_trickplay, args=(library_id, mid), daemon=True).start()
    return True


def start_periodic(interval):
    if interval <= 0:
        return

    def loop():
        while True:
            scan_async()
            time.sleep(interval)

    threading.Thread(target=loop, daemon=True).start()


if __name__ == "__main__":
    from server.db import init_db

    init_db()
    with get_db() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM libraries")]
    for i in ids:
        print(f"biblioteca {i}: {scan_library(i)} novos")
