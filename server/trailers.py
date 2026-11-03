"""64.1: trailers locais de filmes e séries.

Um trailer é um arquivo de vídeo ao lado do item, que NÃO vira item da biblioteca (o scanner continua pulando `*-trailer.*` e a
pasta `trailers/`): `<nome>-trailer.<ext>` (ou `.trailer`, `_trailer`, ` trailer`, ou só `trailer.<ext>`) na pasta do filme/série
ou o primeiro vídeo de uma subpasta `trailers/`. O registro fica na tabela `trailers` (um por filme/série, pela chave de `media`).
64.2: rota `GET /trailer/<movie|show>/<id>` (Range) e o clipe mudo para quem o navegador não toca, gerado só na janela de horário."""
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time

from flask import Blueprint, abort, jsonify, request, send_file, session

import config
from server.auth import login_required
from server.db import get_db, library_folders
from server.i18n import jerr

log = logging.getLogger("starflix.scan")

MAX_SECONDS = 300  # trailer com mais de 5 min não é trailer (provavelmente é o filme): ignorado
_SUFFIX = re.compile(r"(^|[\W_])trailer$", re.I)  # mesmo critério do SKIP_FILE do scanner, só para trailer
_DIRS = {"trailers"}


def _exts():
    from server.scanner import VIDEO_EXTS  # imports tardios: o scanner importa este módulo e o probe/metadata se importam em ciclo
    return VIDEO_EXTS


def _probe(path):
    from server.probe import probe
    return probe(path)


def _key(s):
    return re.sub(r"[\W_]+", "", s or "").lower()


def _videos(d):
    """(nome sem extensão, caminho) dos vídeos que estão diretamente em `d`, em ordem."""
    out = []
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    exts = _exts()
    for f in names:
        stem, ext = os.path.splitext(f)
        p = os.path.join(d, f)
        if not f.startswith(".") and ext.lower() in exts and os.path.isfile(p):
            out.append((stem, p))
    return out


def _dir_of(conn, row, roots):
    """(pasta onde procurar, `flat`): `flat` = o filme está solto na raiz da biblioteca (só vale `<nome>-trailer` do próprio filme).
    Série solta na raiz não tem pasta própria: (None, True)."""
    from server.metadata import _item_dir
    d = _item_dir(conn, row, roots)
    if d:
        return d, False
    if row["path"]:
        return os.path.dirname(row["path"]), True
    return None, True


def find(d, flat, stem=None):
    """Caminho do trailer do item ou None. `stem` = nome do arquivo do filme (sem extensão); séries não têm."""
    files = _videos(d)
    trailers = [(s, p) for s, p in files if _SUFFIX.search(s)]
    others = [(s, p) for s, p in files if not _SUFFIX.search(s)]
    mine = _key(stem)
    # 1) o do próprio item: `<nome>-trailer` (o nome do filme vem primeiro)
    if mine:
        for s, p in trailers:
            if _key(s).startswith(mine):
                return p
    if flat or (stem and len(others) > 1):
        return None  # pasta com vários filmes: um trailer solto não é de ninguém em particular
    # 2) pasta própria: qualquer `*-trailer.*` / `trailer.*`
    if trailers:
        return trailers[0][1]
    # 3) subpasta `trailers/`
    try:
        subs = sorted(x for x in os.listdir(d) if x.lower() in _DIRS and os.path.isdir(os.path.join(d, x)))
    except OSError:
        return None
    for x in subs:
        vids = _videos(os.path.join(d, x))
        if vids:
            return vids[0][1]
    return None


def _full(info):
    """Guarda a análise completa do ffprobe (mesmo formato de `media.info`): a 64.2 precisa de container, codecs, bits e HDR."""
    return json.dumps(info, ensure_ascii=False)


def _is_full(raw):
    return bool(raw) and '"chapters"' in raw  # linhas da V743 guardavam só um resumo: são analisadas de novo


def sync(library_id, media_id=None):
    """Procura o trailer de cada filme/série da biblioteca (ou só de `media_id`) e grava/atualiza/apaga a linha em `trailers`.
    Arquivo igual (caminho, tamanho e data) não é analisado de novo. Pasta indisponível (disco não montado) não apaga nada.
    Nunca derruba o exame: erro vira registro no log. Retorna quantos trailers foram achados ou mudaram."""
    changed = 0
    try:
        with get_db() as conn:
            lib = conn.execute("SELECT type FROM libraries WHERE id = ?", (library_id,)).fetchone()
            if not lib or lib["type"] not in ("movie", "show"):
                return 0
            roots = library_folders(conn, library_id)
            rows = conn.execute("SELECT id, path FROM media WHERE library_id = ? AND (? IS NULL OR id = ?)",
                                (library_id, media_id, media_id)).fetchall()
            have = {r["media_id"]: r for r in conn.execute(
                "SELECT t.media_id, t.path, t.size, t.mtime, t.info FROM trailers t JOIN media m ON m.id = t.media_id WHERE m.library_id = ?",
                (library_id,))}
            for r in rows:
                d, flat = _dir_of(conn, r, roots)
                if not d or not os.path.isdir(d):
                    continue  # sem pasta própria ou disco fora do ar: o que já está gravado fica
                stem = os.path.splitext(os.path.basename(r["path"]))[0] if r["path"] else None
                p = find(d, flat, stem)
                cur = have.get(r["id"])
                if not p:
                    if cur:
                        conn.execute("DELETE FROM trailers WHERE media_id = ?", (r["id"],))
                        conn.commit()
                        changed += 1
                    continue
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                if cur and cur["path"] == p and cur["size"] == st.st_size and abs(cur["mtime"] - st.st_mtime) < 1 and _is_full(cur["info"]):
                    continue
                try:
                    info = _probe(p)
                except Exception:
                    info = None
                dur = (info or {}).get("duration") or 0
                if not info or not info.get("video") or dur <= 0 or dur > MAX_SECONDS:
                    log.info("trailer ignorado (%s): %s", "ilegível" if not info or not info.get("video") else f"{dur:.0f} s", p)
                    if cur:
                        conn.execute("DELETE FROM trailers WHERE media_id = ?", (r["id"],))
                        conn.commit()
                        changed += 1
                    continue
                if cur and (cur["path"] != p or cur["size"] != st.st_size or abs(cur["mtime"] - st.st_mtime) >= 1):
                    conn.execute("DELETE FROM trailer_clips WHERE media_id = ?", (r["id"],))  # arquivo mudou: o clipe antigo não vale
                conn.execute(
                    "INSERT INTO trailers (media_id, path, duration, size, mtime, info) VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(media_id) DO UPDATE SET path = excluded.path, duration = excluded.duration, size = excluded.size, "
                    "mtime = excluded.mtime, info = excluded.info, found_at = CURRENT_TIMESTAMP",
                    (r["id"], p, round(dur, 2), st.st_size, st.st_mtime, _full(info)))
                conn.commit()
                changed += 1
    except Exception:
        log.exception("falha ao procurar trailers da biblioteca %s", library_id)
    return changed


def prune(conn, library_id, only, gone):
    """Chamado por `prune_missing`: apaga a linha de trailer cujo arquivo sumiu (`gone` já poupa pastas indisponíveis)."""
    n = 0
    for r in conn.execute(
            "SELECT t.media_id, t.path FROM trailers t JOIN media m ON m.id = t.media_id WHERE m.library_id = ? AND (? IS NULL OR m.id = ?)",
            (library_id, only, only)).fetchall():
        if gone(r["path"]):
            conn.execute("DELETE FROM trailers WHERE media_id = ?", (r["media_id"],))
            conn.commit()
            n += 1
    return n


# ---- 64.2: tocar o trailer (direto ou clipe mudo) ----
CLIP_SECONDS = 45
CLIP_HEIGHT = 720
MAX_TRIES = 3
_DIRECT = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/mp4", ".webm": "video/webm"}
_AUDIO_OK = {None, "aac", "mp3", "opus", "vorbis", "flac"}  # o vídeo toca mudo, mas o navegador ainda lê a faixa de áudio

bp = Blueprint("trailers", __name__)


def _codec(x):
    return (x.get("codec") if isinstance(x, dict) else x) or None


def direct_ok(path, info):
    """True se o navegador toca o arquivo do trailer como está (mp4/mov H.264 8 bits ou webm VP8/VP9, sem HDR, áudio comum)."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in _DIRECT or not info:
        return False
    v = info.get("video")
    codec, bits = _codec(v), (v.get("bits") if isinstance(v, dict) else None)
    if (v.get("hdr", "none") if isinstance(v, dict) else "none") != "none" or bits not in (None, 8):
        return False
    audio = info.get("audio") or []
    if audio and _codec(audio[0]) not in _AUDIO_OK:
        return False
    if ext == ".webm":
        return codec in ("vp8", "vp9")
    return codec == "h264" and "mp4" in str(info.get("container") or "").split(",")


def clip_path(media_id):
    return os.path.join(config.TRAILERS_DIR, f"{int(media_id)}.mp4")


def _clip_valid(row, t):
    """Linha `ok` do clipe ainda vale: o arquivo existe e o trailer de origem não mudou."""
    return bool(row) and row["status"] == "ok" and row["out_path"] and os.path.isfile(row["out_path"]) \
        and row["src_size"] == t["size"] and abs(row["src_mtime"] - t["mtime"]) < 1


def _load(info_raw):
    try:
        return json.loads(info_raw) if info_raw else None
    except ValueError:
        return None


def enabled(conn):
    """64.4: interruptor global (Configurações → Reprodução, `settings.trailer_global`; padrão ligado)."""
    r = conn.execute("SELECT value FROM settings WHERE key = 'trailer_global'").fetchone()  # sem importar libraries (importação circular)
    return not (r and str(r["value"]) == "0")


def status(conn, media_id):
    """64.4: o que a página do item (admin) mostra sobre o trailer: None (sem trailer) ou
    `direct` (toca o arquivo), `clip` (clipe mudo pronto), `pending` (clipe será gerado de madrugada) ou `fail`."""
    r = conn.execute("SELECT path, size, mtime, info FROM trailers WHERE media_id = ?", (media_id,)).fetchone()
    if not r or not os.path.isfile(r["path"]):
        return None
    info = _load(r["info"])
    if info and direct_ok(r["path"], info):
        return "direct"
    c = conn.execute("SELECT * FROM trailer_clips WHERE media_id = ?", (media_id,)).fetchone()
    if _clip_valid(c, r):
        return "clip"
    if c and c["status"] == "fail" and c["tries"] >= MAX_TRIES and c["src_size"] == r["size"] and abs(c["src_mtime"] - r["mtime"]) < 1:
        return "fail"
    return "pending"


@bp.route("/trailer/<kind>/<int:item_id>")
@login_required
def trailer(kind, item_id):
    """Trailer mudo do filme (`movie`) ou da série (`show`), com Range (206). Toca o arquivo local quando o navegador aceita;
    senão, o clipe mudo já gerado. Sem trailer, sem clipe ainda, sem acesso à biblioteca ou item de outro tipo: 404 (nada é convertido aqui)."""
    from server.libraries import can_access
    if kind not in ("movie", "show"):
        abort(404)
    with get_db() as conn:
        if not enabled(conn):
            abort(404)
        r = conn.execute(
            "SELECT t.path, t.size, t.mtime, t.info, m.library_id, m.path AS mpath FROM trailers t JOIN media m ON m.id = t.media_id WHERE t.media_id = ?",
            (item_id,)).fetchone()
        clip = conn.execute("SELECT * FROM trailer_clips WHERE media_id = ?", (item_id,)).fetchone() if r else None
    if not r or (kind == "movie") != bool(r["mpath"]) or not can_access(session["user_id"], r["library_id"]) or not os.path.isfile(r["path"]):
        abort(404)
    if direct_ok(r["path"], _load(r["info"])):
        out, mime = r["path"], _DIRECT[os.path.splitext(r["path"])[1].lower()]
    elif _clip_valid(clip, r):
        out, mime = clip["out_path"], "video/mp4"
    else:
        abort(404)
    resp = send_file(out, mimetype=mime, conditional=True, max_age=0)
    resp.headers["Accept-Ranges"] = "bytes"
    return resp


HAS_MAX = 100  # 65.1: itens por pedido em /trailers/has


@bp.route("/trailers/has", methods=["POST"])
@login_required
def has():
    """65.1: recebe até 100 itens `{kind, id}` (`movie`/`show`) e devolve `{has: [{kind, id}]}` só com os que têm trailer
    **pronto para tocar** (arquivo local aceito pelo navegador ou clipe mudo já gerado), nas bibliotecas liberadas ao perfil.
    Interruptor global desligado = lista vazia. Item inexistente, de outro tipo ou sem acesso simplesmente não aparece."""
    from server.libraries import visible_libraries
    from server.tv_auth import rate_ok
    if not rate_ok("trailers-has", request.remote_addr or "?", 60, 60):
        return jerr("err.muitos_pedidos_tente_novo_instantes", 429)
    items = (request.get_json(silent=True) or {}).get("items")
    if not isinstance(items, list) or len(items) > HAS_MAX:
        return jerr("err.pedido_invalido", 400)
    want, seen = [], set()
    for it in items:
        kind, iid = (it.get("kind"), it.get("id")) if isinstance(it, dict) else (None, None)
        if kind not in ("movie", "show") or isinstance(iid, bool) or not isinstance(iid, int):
            return jerr("err.pedido_invalido", 400)
        if (kind, iid) not in seen:
            seen.add((kind, iid))
            want.append((kind, iid))
    if not want:
        return jsonify(has=[])
    libs = {l["id"] for l in visible_libraries(session["user_id"])}
    out = []
    with get_db() as conn:
        if not enabled(conn):
            return jsonify(has=[])
        for kind, iid in want:
            m = conn.execute("SELECT library_id, path FROM media WHERE id = ?", (iid,)).fetchone()
            if not m or m["library_id"] not in libs or (kind == "movie") != bool(m["path"]):
                continue
            if status(conn, iid) in ("direct", "clip"):
                out.append({"kind": kind, "id": iid})
    return jsonify(has=out)


def build_cmd(src, info, part):
    """(comando ffmpeg, motivo de recusa): só vídeo (sem áudio), até 45 s, 720p, H.264 8 bits. HDR só com filtro de tone-map."""
    from server.stream import tonemap_chain
    v = (info or {}).get("video") or {}
    if not isinstance(v, dict):
        return None, "análise incompleta"  # i18n-ok: motivo técnico gravado em trailer_clips.reason (log), não aparece na interface
    if v.get("hdr", "none") != "none":
        vf = tonemap_chain(info, None, CLIP_HEIGHT)
        if not vf:
            return None, "HDR sem filtro de tone-map no ffmpeg"
    else:
        vf = f"scale=-2:'min({CLIP_HEIGHT},ih)'"
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-t", str(CLIP_SECONDS), "-i", src, "-map", "0:v:0", "-an", "-sn", "-dn",
           "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-profile:v", "high", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", "-f", "mp4", part]
    low = ([ "nice", "-n", "19"] if shutil.which("nice") else []) + (["ionice", "-c3"] if shutil.which("ionice") else [])
    return low + cmd, ""


def _verify(path):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
                             capture_output=True, text=True, timeout=60)
        data = json.loads(out.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return False, "ffprobe falhou no clipe"
    streams = data.get("streams") or []
    if not any(x.get("codec_type") == "video" and x.get("codec_name") == "h264" for x in streams):
        return False, "clipe sem vídeo H.264"  # i18n-ok: motivo técnico gravado em trailer_clips.reason (log), não aparece na interface
    if any(x.get("codec_type") == "audio" for x in streams):
        return False, "clipe com áudio"  # i18n-ok: motivo técnico gravado em trailer_clips.reason (log), não aparece na interface
    if float((data.get("format") or {}).get("duration") or 0) < 0.5:
        return False, "clipe vazio"
    return True, ""


def _save_clip(conn, media_id, t, status, out="", size=0, reason="", tries=0):
    conn.execute(
        "INSERT INTO trailer_clips (media_id, status, out_path, out_size, src_size, src_mtime, reason, tries) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(media_id) DO UPDATE SET status = excluded.status, out_path = excluded.out_path, out_size = excluded.out_size, "
        "src_size = excluded.src_size, src_mtime = excluded.src_mtime, reason = excluded.reason, tries = excluded.tries, made_at = CURRENT_TIMESTAMP",
        (media_id, status, out, size, t["size"], t["mtime"], reason, tries))
    conn.commit()


def make_clip(media_id):
    """Gera (uma vez) o clipe mudo do trailer de `media_id`. Escreve em `.part`, confere com o ffprobe e só então renomeia."""
    with get_db() as conn:
        t = conn.execute("SELECT media_id, path, size, mtime, info FROM trailers WHERE media_id = ?", (media_id,)).fetchone()
        old = conn.execute("SELECT tries FROM trailer_clips WHERE media_id = ?", (media_id,)).fetchone()
    if not t or not os.path.isfile(t["path"]):
        return "gone"
    tries = (old["tries"] if old else 0) + 1
    info = _load(t["info"])
    out = clip_path(media_id)
    part = out + ".part"
    os.makedirs(config.TRAILERS_DIR, exist_ok=True)
    cmd, why = build_cmd(t["path"], info, part)
    ok = False
    if cmd:
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            ok, why = (_verify(part) if res.returncode == 0 and os.path.isfile(part) else (False, (res.stderr or "ffmpeg falhou").strip()[-200:]))
        except (OSError, subprocess.SubprocessError) as e:
            why = f"ffmpeg: {e}"
    with get_db() as conn:
        if ok:
            os.replace(part, out)
            _save_clip(conn, media_id, t, "ok", out, os.path.getsize(out), "", 0)
        else:
            _rm(part)
            # recusa definitiva (HDR sem tone-map, análise antiga) gasta todas as tentativas de uma vez
            _save_clip(conn, media_id, t, "fail", "", 0, why, MAX_TRIES if not cmd else tries)
            log.info("clipe do trailer %s não gerado: %s", media_id, why)
    return "ok" if ok else "fail"


def _rm(path):
    try:
        os.remove(path)
    except OSError:
        pass


def pending(conn):
    """Trailers que o navegador não toca como estão e ainda não têm clipe válido (e não esgotaram as tentativas)."""
    out = []
    for t in conn.execute("SELECT t.media_id, t.path, t.size, t.mtime, t.info FROM trailers t JOIN media m ON m.id = t.media_id ORDER BY t.media_id"):
        info = _load(t["info"])
        if not info or direct_ok(t["path"], info):
            continue
        c = conn.execute("SELECT * FROM trailer_clips WHERE media_id = ?", (t["media_id"],)).fetchone()
        if _clip_valid(c, t) or (c and c["status"] == "fail" and c["tries"] >= MAX_TRIES and c["src_size"] == t["size"] and abs(c["src_mtime"] - t["mtime"]) < 1):
            continue
        out.append(t["media_id"])
    return out


_STATE = {"thread": None}


def running():
    t = _STATE["thread"]
    return bool(t and t.is_alive())


def tick(now=None):
    """Chamado 1×/min por `stream.start_cleanup`: um clipe por vez, só na janela de horário da otimização (a mesma, 02:00-07:00 por padrão),
    com a otimização parada, sem ninguém em transcode e com disco livre. Nada é gerado na hora de assistir."""
    from server import optimize
    if running() or optimize.running() or optimize.STATE.get("paused") or optimize._transcoding():
        return None
    with get_db() as conn:
        window, _ = optimize._settings(conn)
        if not optimize.in_window(window, now):
            return None
        todo = pending(conn)
    if not todo:
        return None
    if config.MIN_FREE_GB > 0:
        os.makedirs(config.TRAILERS_DIR, exist_ok=True)
        if shutil.disk_usage(config.TRAILERS_DIR).free < config.MIN_FREE_GB * 1024 ** 3:
            return None
    mid = todo[0]

    def work():
        try:
            make_clip(mid)
        except Exception:  # noqa: BLE001
            log.exception("falha ao gerar o clipe do trailer %s", mid)

    _STATE["thread"] = threading.Thread(target=work, daemon=True)
    _STATE["thread"].start()
    return mid


def prune_clips():
    """Apaga os clipes (e `.part`) sem linha `ok` em `trailer_clips` (trailer ou item que saiu do banco). Chamado por `prune_missing`."""
    if not os.path.isdir(config.TRAILERS_DIR):
        return 0
    with get_db() as conn:
        keep = {os.path.basename(r["out_path"]) for r in conn.execute("SELECT out_path FROM trailer_clips WHERE status = 'ok' AND out_path IS NOT NULL")}
    n = 0
    for f in os.listdir(config.TRAILERS_DIR):
        if f not in keep:
            _rm(os.path.join(config.TRAILERS_DIR, f))
            n += 1
    return n
