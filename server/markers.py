"""Marcadores de abertura e créditos dos episódios (48.1; marcação manual na 48.3)."""
import array
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import time

from flask import Blueprint, jsonify, request

from server.auth import admin_required, login_required
from server.db import get_db
from server import scanstate

log = logging.getLogger("starflix.scan")  # 53.5: mesmo log do exame (journal)
from server.stream import get_item
from server.i18n import jerr

bp = Blueprint("markers", __name__)

KINDS = ("intro", "credits")
_INTRO = re.compile(r"\b(intro|introduction|introdu[cç][aã]o|opening|abertura|op)\b", re.I)
_CREDITS = re.compile(r"\b(credits?|cr[eé]ditos?|ending|encerramento|end credits|ed)\b", re.I)
INTRO_MIN, INTRO_MAX = 5.0, 240.0  # duração plausível de uma abertura (s)


def from_chapters(info):
    """{kind: (início, fim)} a partir dos capítulos do ffprobe com nome de abertura/créditos."""
    out = {}
    if not isinstance(info, dict):
        return out
    dur = float(info.get("duration") or 0)
    for c in info.get("chapters") or []:
        try:
            s, e, t = float(c["start"]), float(c["end"]), str(c.get("title") or "")
        except (KeyError, TypeError, ValueError):
            continue
        if e <= s:
            continue
        if "intro" not in out and _INTRO.search(t) and INTRO_MIN <= e - s <= INTRO_MAX:
            out["intro"] = (round(s, 2), round(e, 2))
        elif "credits" not in out and _CREDITS.search(t) and (not dur or s > dur * 0.5):
            out["credits"] = (round(s, 2), round(e, 2))
    return out


def sync_episode(conn, episode_id, info):
    """Atualiza os marcadores vindos de capítulos; nunca mexe em marcador manual."""
    found = from_chapters(info)
    have = {r["kind"]: r["source"] for r in conn.execute("SELECT kind, source FROM episode_markers WHERE episode_id = ?", (episode_id,))}
    for kind in KINDS:
        if have.get(kind) == "manual":
            continue
        if kind in found:
            s, e = found[kind]
            conn.execute(
                "INSERT INTO episode_markers (episode_id, kind, start, end, source, confidence) VALUES (?, ?, ?, ?, 'chapter', 1) "
                "ON CONFLICT(episode_id, kind) DO UPDATE SET start = excluded.start, end = excluded.end, source = 'chapter', confidence = 1",
                (episode_id, kind, s, e))
        elif have.get(kind) == "chapter":
            conn.execute("DELETE FROM episode_markers WHERE episode_id = ? AND kind = ?", (episode_id, kind))


FALLBACK_CREDITS = 45  # 57.22: sem marcador de créditos, o "Próximo episódio" aparece nos últimos 45 s


def credits_fallback(info):
    """Início assumido dos créditos sem marcador: 45 s antes do fim (90 % em vídeo curto); None se a duração é curta ou desconhecida."""
    try:
        dur = float((info or {}).get("duration") or 0) if isinstance(info, dict) else 0
    except (TypeError, ValueError):
        return None
    return round(max(dur - FALLBACK_CREDITS, dur * 0.9), 2) if dur >= 300 else None


@bp.route("/markers/episode/<int:episode_id>")
@login_required
def episode_markers(episode_id):
    _, info = get_item("episode", episode_id)  # valida acesso e arquivo (404)
    with get_db() as conn:
        if from_chapters(info):  # episódio analisado antes da 48.1 ou com capítulos novos
            sync_episode(conn, episode_id, info)
        rows = conn.execute("SELECT kind, start, end, source, confidence FROM episode_markers WHERE episode_id = ? ORDER BY start",
                            (episode_id,)).fetchall()
    has_credits = any(r["kind"] == "credits" for r in rows)
    return jsonify(markers=[{"kind": r["kind"], "start": r["start"], "end": r["end"], "source": r["source"],
                             "confidence": r["confidence"]} for r in rows],
                   credits_fallback=None if has_credits else credits_fallback(info))


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError
    if not math.isfinite(f):
        raise ValueError
    return round(f, 2)


def _duration(info_text):
    try:
        return float((json.loads(info_text) if info_text else {}).get("duration") or 0)
    except (TypeError, ValueError, AttributeError):
        return 0.0


def _put(conn, episode_id, kind, start, end):
    conn.execute(
        "INSERT INTO episode_markers (episode_id, kind, start, end, source, confidence) VALUES (?, ?, ?, ?, 'manual', 1) "
        "ON CONFLICT(episode_id, kind) DO UPDATE SET start = excluded.start, end = excluded.end, source = 'manual', confidence = 1",
        (episode_id, kind, start, end))


@bp.route("/admin/markers/episode/<int:episode_id>", methods=["POST"])
@admin_required
def set_marker(episode_id):
    """Marcação manual (48.3): {kind, start, end} grava; {kind, delete: true} remove."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or body.get("kind") not in KINDS:
        return jerr("err.dados_invalidos", 400)
    kind = body["kind"]
    with get_db() as conn:
        ep = conn.execute("SELECT info FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        if not ep:
            return jerr("err.episodio_nao_encontrado", 404)
        if body.get("delete"):
            conn.execute("DELETE FROM episode_markers WHERE episode_id = ? AND kind = ?", (episode_id, kind))
            return jsonify(ok=True, marker=None)
        try:
            start, end = _num(body.get("start")), _num(body.get("end"))
        except ValueError:
            return jerr("err.tempo_invalido", 400)
        dur = _duration(ep["info"])
        if start < 0 or end <= start or (dur and end > dur + 1):
            return jerr("err.fim_precisa_ser_maior_que", 400)
        _put(conn, episode_id, kind, start, end)
    return jsonify(ok=True, marker={"kind": kind, "start": start, "end": end, "source": "manual", "confidence": 1})


@bp.route("/admin/markers/episode/<int:episode_id>/season", methods=["POST"])
@admin_required
def apply_season(episode_id):
    """Copia o marcador deste episódio para os outros da temporada, com deslocamento opcional em segundos (48.3)."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or body.get("kind") not in KINDS:
        return jerr("err.dados_invalidos", 400)
    kind = body["kind"]
    try:
        shift = _num(body.get("shift") or 0)
    except ValueError:
        return jerr("err.deslocamento_invalido", 400)
    if abs(shift) > 600:
        return jerr("err.deslocamento_maximo_600_s", 400)
    with get_db() as conn:
        ep = conn.execute("SELECT media_id, season FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        if not ep:
            return jerr("err.episodio_nao_encontrado", 404)
        m = conn.execute("SELECT start, end FROM episode_markers WHERE episode_id = ? AND kind = ?", (episode_id, kind)).fetchone()
        if not m:
            return jerr("err.este_episodio_ainda_nao_tem", 400)
        n = 0
        for o in conn.execute("SELECT id, info FROM episodes WHERE media_id = ? AND season = ? AND id != ?",
                              (ep["media_id"], ep["season"], episode_id)).fetchall():
            start, end, dur = max(0.0, m["start"] + shift), m["end"] + shift, _duration(o["info"])
            if dur:
                end = min(end, dur)
            if end - start < 1:
                continue
            _put(conn, o["id"], kind, round(start, 2), round(end, 2))
            n += 1
    return jsonify(ok=True, count=n)


# ---------- 48.5: detecção automática (abertura por impressão de áudio; créditos por tela preta) ----------
DT = 0.1238          # segundos por item do chromaprint
FP_SECONDS = 600     # só os primeiros 10 min de cada episódio
MIN_INTRO, MAX_INTRO = 15.0, 120.0
MIN_CONF = 0.6       # fração de itens parecidos dentro do trecho achado
HAMMING = 6          # bits diferentes (de 32) que ainda contam como "parecido"
GAP = 16             # buracos de até ~2 s dentro do trecho comum são aceitos


_TOOLS = []  # 53.4: resultado guardado (o painel chamava `ffmpeg -muxers` a cada abertura, e travava com o servidor ocupado)


def tools():
    """Quem gera a impressão de áudio: 'fpcalc', 'ffmpeg' (muxer chromaprint) ou None."""
    if _TOOLS:
        return _TOOLS[0]
    r = None
    if shutil.which("fpcalc"):
        r = "fpcalc"
    elif shutil.which("ffmpeg"):
        try:
            out = subprocess.run(["ffmpeg", "-hide_banner", "-muxers"], capture_output=True, text=True, timeout=15).stdout
            if "chromaprint" in out:
                r = "ffmpeg"
        except (OSError, subprocess.SubprocessError):
            return None  # falha passageira: não guarda
    _TOOLS.append(r)
    return r


def _nice(cmd):
    """53.4: CPU e disco no mínimo (nice 19 + ionice ocioso) para a detecção não sufocar o servidor web."""
    pre = ["ionice", "-c3"] if shutil.which("ionice") else []
    return pre + (["nice", "-n", "19"] if shutil.which("nice") else []) + cmd


def fingerprint(path, how=None):
    """Lista de inteiros de 32 bits dos primeiros FP_SECONDS do áudio; None se falhar."""
    how = how or tools()
    try:
        if how == "fpcalc":
            out = subprocess.run(_nice(["fpcalc", "-raw", "-length", str(FP_SECONDS), path]), capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL).stdout
            for line in out.splitlines():
                if line.startswith("FINGERPRINT="):
                    return [int(x) & 0xFFFFFFFF for x in line[12:].split(",") if x.strip()] or None
            return None
        if how == "ffmpeg":
            r = subprocess.run(_nice(["ffmpeg", "-nostdin", "-threads", "1", "-v", "error", "-t", str(FP_SECONDS), "-i", path, "-map", "0:a:0", "-vn", "-ac", "1",
                                      "-ar", "11025", "-f", "chromaprint", "-fp_format", "raw", "-"]), capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
            b = r.stdout[:len(r.stdout) // 4 * 4]
            if not b:
                return None
            a = array.array("I")
            a.frombytes(b)
            if sys.byteorder == "big":
                a.byteswap()
            return list(a)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return None


def _pop(x):
    return bin(x).count("1")


def common_segment(a, b):
    """Maior trecho de áudio igual entre duas impressões. Devolve (início_a, fim_a, início_b, fim_b, confiança) em segundos ou None."""
    if not a or not b or len(a) < 100 or len(b) < 100:
        return None
    index = {}  # índice pelas duas metades de 16 bits: tolera o ruído da codificação
    for i, v in enumerate(a):
        index.setdefault((0, v >> 16), []).append(i)
        index.setdefault((1, v & 0xFFFF), []).append(i)
    votes = {}
    for j, v in enumerate(b):
        for key in ((0, v >> 16), (1, v & 0xFFFF)):
            pos = index.get(key)
            if pos and len(pos) <= 8:  # valor repetido demais (silêncio, tom contínuo) não identifica nada
                for i in pos:
                    votes[i - j] = votes.get(i - j, 0) + 1
    if not votes:
        return None
    off, n = max(votes.items(), key=lambda kv: kv[1])
    if n < 40:
        return None
    # alinhados por `off` (i = j + off): marca onde as duas são parecidas
    lo, hi = max(0, -off), min(len(b), len(a) - off)
    if hi - lo < 100:
        return None
    ok = [_pop(a[j + off] ^ b[j]) <= HAMMING for j in range(lo, hi)]
    best, run_s, last, hits = None, None, None, 0
    for k, m in enumerate(ok + [False] * (GAP + 2)):  # sentinela fecha o último trecho
        if m:
            if run_s is None:
                run_s, hits = k, 0
            last = k
            hits += 1
        elif run_s is not None and k - last > GAP:
            if best is None or last - run_s > best[1] - best[0]:
                best = (run_s, last, hits)
            run_s = None
    if not best:
        return None
    s0, e0, h = best
    length = (e0 - s0 + 1) * DT
    conf = h / (e0 - s0 + 1)
    if not MIN_INTRO <= length <= MAX_INTRO or conf < MIN_CONF:
        return None
    ja, jb = lo + s0, lo + e0 + 1
    return (round((ja + off) * DT, 2), round((jb + off) * DT, 2), round(ja * DT, 2), round(jb * DT, 2), round(conf, 2))


def _black_credits(path, dur):
    """Início dos créditos: último trecho de tela preta que começa na parte final do episódio (confiança baixa)."""
    if not shutil.which("ffmpeg") or dur < 300:
        return None
    win = min(360.0, dur * 0.25)
    start = dur - win
    try:
        r = subprocess.run(_nice(["ffmpeg", "-nostdin", "-threads", "1", "-hide_banner", "-skip_frame", "nokey", "-ss", f"{start:.1f}", "-i", path, "-an", "-sn",
                                  "-vf", "blackdetect=d=0.8:pix_th=0.10", "-f", "null", "-"]), capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        log.warning("créditos: ffmpeg falhou/estourou o tempo em %s", path)
        return None
    cand = None
    for m in re.finditer(r"black_start:([\d.]+)", r.stderr):
        t = start + float(m.group(1))
        if t <= dur - 20:
            cand = t
    return round(cand, 2) if cand else None


def _set_auto(conn, ep, kind, s, e, conf):
    """Grava marcador automático sem tocar em manual/capítulo; sem resultado, limpa o automático antigo."""
    have = conn.execute("SELECT source FROM episode_markers WHERE episode_id = ? AND kind = ?", (ep, kind)).fetchone()
    if have and have["source"] in ("manual", "chapter"):
        return
    if s is None:
        if have:
            conn.execute("DELETE FROM episode_markers WHERE episode_id = ? AND kind = ?", (ep, kind))
        return
    conn.execute(
        "INSERT INTO episode_markers (episode_id, kind, start, end, source, confidence) VALUES (?, ?, ?, ?, 'auto', ?) "
        "ON CONFLICT(episode_id, kind) DO UPDATE SET start = excluded.start, end = excluded.end, source = 'auto', confidence = excluded.confidence",
        (ep, kind, s, e, conf))


def _refs(media_id, season, how, limit=2):
    """57.22: impressões de áudio de até 2 episódios de outras temporadas da série (temporada de 1 arquivo ou episódio sem par entre os vizinhos)."""
    with get_db() as conn:
        rows = [r["path"] for r in conn.execute(
            "SELECT path FROM episodes WHERE media_id = ? AND season > 0 AND season != ? AND path IS NOT NULL ORDER BY ABS(season - ?), season, episode, id",
            (media_id, season, season))]
    out, seen = [], set()
    for p in rows:
        if p in seen or not os.path.isfile(p):
            continue
        seen.add(p)
        out.append(fingerprint(p, how))
        time.sleep(0.5)
        if len(out) >= limit:
            break
    return out


def _lacks_intro(media_id, season):
    with get_db() as conn:
        return conn.execute(
            "SELECT 1 FROM episodes e WHERE e.media_id = ? AND e.season = ? AND e.path IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM episode_markers m WHERE m.episode_id = e.id AND m.kind = 'intro') LIMIT 1", (media_id, season)).fetchone() is not None


SCAN_V = 1_000_000  # 57.22: somado ao `n` guardado em marker_scan; linha antiga (sem a soma) só refaz a temporada que ficou sem abertura


def detect_season(media_id, season, how=None):
    """Aberturas (impressão de áudio entre vizinhos) e créditos (tela preta) de uma temporada. Devolve quantos marcadores gravou."""
    how = how or tools()
    with get_db() as conn:
        eps = [dict(r) for r in conn.execute("SELECT id, path, info FROM episodes WHERE media_id = ? AND season = ? ORDER BY episode, id", (media_id, season))]
    eps = [e for e in eps if e["path"] and os.path.isfile(e["path"])]
    seen, uniq = set(), []
    for e in eps:  # arquivo de vários episódios entra uma vez
        if e["path"] not in seen:
            seen.add(e["path"]); uniq.append(e)
    eps = uniq
    found = 0
    if how and len(eps) >= 1:
        fps = []
        log.info("aberturas: temporada %s do item %s — %d arquivo(s)", season, media_id, len(eps))
        for e in eps:
            scanstate.set_current(media_id)
            t0 = time.time()
            fps.append(fingerprint(e["path"], how))
            log.info("aberturas: impressão de áudio em %.1f s — %s", time.time() - t0, os.path.basename(e["path"]))
            time.sleep(0.5)  # 53.4: respiro entre arquivos
        t0 = time.time()
        log.info("aberturas: comparando %d impressões…", len(fps))
        refs = None
        for i, e in enumerate(eps):
            res = None
            for j in (i + 1, i - 1, i + 2, i - 2, i + 3):
                if 0 <= j < len(eps) and j != i:
                    seg = common_segment(fps[i], fps[j])
                    if seg:
                        res = seg
                        break
            if not res:  # 57.22: sem par entre os vizinhos: compara com episódios de outras temporadas
                if refs is None:
                    refs = _refs(media_id, season, how)
                for fr in refs:
                    seg = common_segment(fps[i], fr)
                    if seg:
                        res = seg
                        break
            with get_db() as conn:
                if res:
                    _set_auto(conn, e["id"], "intro", res[0], res[1], res[4])
                    found += 1
                else:
                    _set_auto(conn, e["id"], "intro", None, None, 0)
        log.info("aberturas: comparação concluída em %.1f s (%d achada(s))", time.time() - t0, found)
    for e in eps:
        scanstate.set_current(media_id)
        dur = _duration(e["info"])
        with get_db() as conn:
            have = conn.execute("SELECT source FROM episode_markers WHERE episode_id = ? AND kind = 'credits'", (e["id"],)).fetchone()
        if have and have["source"] in ("manual", "chapter"):
            continue
        t0 = time.time()
        t = _black_credits(e["path"], dur) if dur else None
        log.info("créditos: tela preta em %.1f s — %s", time.time() - t0, os.path.basename(e["path"]))
        time.sleep(0.5)
        with get_db() as conn:
            if t:
                _set_auto(conn, e["id"], "credits", t, round(dur, 2), 0.5)
                found += 1
            else:
                _set_auto(conn, e["id"], "credits", None, None, 0)
    return found


def detect_markers(library_id, media_id=None):
    """Etapa \"Detectando aberturas\" do exame: refaz só a temporada nova ou que ganhou/perdeu episódio (`marker_scan`)."""
    from server.db import lib_prefs
    with get_db() as conn:
        lib = conn.execute("SELECT type, prefs FROM libraries WHERE id = ?", (library_id,)).fetchone()
        if not lib or lib["type"] != "show" or not lib_prefs(lib)["detect_markers"]:
            return 0
        q = ("SELECT media_id, season, COUNT(DISTINCT path) AS n FROM episodes WHERE media_id IN (SELECT id FROM media WHERE library_id = ?) "
             "AND path IS NOT NULL" + (" AND media_id = ?" if media_id else "") + " GROUP BY media_id, season")
        seasons = conn.execute(q, (library_id, media_id) if media_id else (library_id,)).fetchall()
        done = {(r["media_id"], r["season"]): r["n"] for r in conn.execute("SELECT media_id, season, n FROM marker_scan")}
    how = tools()
    total = 0
    for r in seasons:
        key = (r["media_id"], r["season"])
        want, old = r["n"] + SCAN_V, done.get(key)
        if old == want:
            continue
        if old == r["n"] and not _lacks_intro(*key):  # detecção antiga que já cobria todos os episódios: só marca a versão nova
            with get_db() as conn:
                conn.execute("UPDATE marker_scan SET n = ? WHERE media_id = ? AND season = ?", (want, key[0], key[1]))
            continue
        if scanstate.cancelled(library_id):
            raise scanstate.ScanCancelled()
        total += detect_season(r["media_id"], r["season"], how)
        with get_db() as conn:
            conn.execute("INSERT INTO marker_scan (media_id, season, n) VALUES (?, ?, ?) ON CONFLICT(media_id, season) DO UPDATE SET n = excluded.n",
                         (r["media_id"], r["season"], want))
    return total
