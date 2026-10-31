import json
import math
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import threading
import time

from urllib.parse import quote

from flask import Blueprint, Response, abort, jsonify, request, send_file, send_from_directory, session

import config

from server.auth import login_required
from server.db import get_db, library_folders
from server.caps import parse_caps
from server.libraries import can_access
from server.i18n import jerr

bp = Blueprint("stream", __name__)

MIMES = {
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/mp4",
    ".webm": "video/webm", ".mkv": "video/x-matroska", ".avi": "video/x-msvideo",
}
# compatíveis com <video> nos navegadores
VIDEO_OK = {"mp4": {"h264", "av1", "vp9"}, "mkv": {"h264", "av1", "vp9", "vp8"}, "webm": {"vp8", "vp9", "av1"}}
AUDIO_OK = {"aac", "mp3", "opus", "vorbis", "flac"}


def _kind(path):
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    return {"m4v": "mp4", "mov": "mp4"}.get(ext, ext)


_HIGH_BIT = re.compile(r"(?:p|gray)(?:9|10|12|14|16)(?:le|be)?$|^p0(?:10|12|16)(?:le|be)?$")


_NOT_420 = re.compile(r"^(?:yuvj?(?:411|422|440|444)p|gbrp|gbra|rgb|bgr|0rgb|rgb0|bgr0|argb|rgba|abgr|bgra)")


def is_10bit(video):
    """True para vídeo com mais de 8 bits (ex.: yuv420p10le, Hi10P)."""
    return bool(_HIGH_BIT.search((video or {}).get("pix_fmt") or ""))


def is_bad_pix(video):
    """True se o navegador/MediaCodec não decodifica o formato de pixel: mais de 8 bits ou croma 4:2:2/4:4:4 (Hi422/Hi444)."""
    return is_10bit(video) or bool(_NOT_420.search((video or {}).get("pix_fmt") or ""))


def can_direct_play(path, info, caps=None):
    """True se o arquivo (container + codecs) toca direto no aparelho. Sem `caps` vale a lista fixa de navegador de antes."""
    return _direct_why(path, info, caps)[0]


def _direct_why(path, info, caps=None):
    """(ok, motivo): 52.1 — `caps` (caps.py) troca as listas fixas pelas capacidades informadas pelo aparelho."""
    if not info or info.get("error") or not info.get("video"):
        return False, "sem análise do arquivo"
    v = info["video"]
    audio = info.get("audio") or []
    a0 = audio[0] if audio else None  # o aparelho toca apenas a primeira faixa de áudio
    if caps is None:
        allowed = VIDEO_OK.get(_kind(path))
        if is_bad_pix(v):
            return False, "pixel " + str(v.get("pix_fmt"))
        if not allowed or v.get("codec") not in allowed:
            return False, f"vídeo {v.get('codec')} em {_kind(path)}"
        if a0 and a0.get("codec") not in AUDIO_OK:
            return False, f"áudio {a0.get('codec')}"
        return True, f"{v.get('codec')} ok" + (f", {a0.get('codec')} ok" if a0 else "")
    if _kind(path) not in caps.c:
        return False, f"contêiner {_kind(path)}"
    if v.get("codec") not in caps.v:
        return False, f"vídeo {v.get('codec')}"
    if _NOT_420.search(v.get("pix_fmt") or ""):
        return False, "pixel " + str(v.get("pix_fmt"))
    if is_10bit(v) and (not caps.b10 or v.get("codec") == "h264"):  # Hi10P não tem decodificador de hardware/navegador
        return False, "10 bits"
    if v.get("hdr", "none") != "none" and not caps.hdr:
        return False, "HDR"
    if a0 and a0.get("codec") not in caps.a:
        return False, f"áudio {a0.get('codec')}"
    if a0 and (a0.get("channels") or 2) > caps.ch:
        return False, f"áudio {a0.get('channels')} canais"
    return True, f"{v.get('codec')} ok" + (f", {a0.get('codec')} ok" if a0 else "")


def audio_arg(info):
    """Índice (ffprobe) da faixa de áudio pedida em ?audio=; None = padrão. 400 se inválido."""
    a = request.args.get("audio", type=int)
    if a is None:
        return None
    if not info or a not in [t["index"] for t in info.get("audio") or []]:
        abort(400)
    return a


def start_arg(info=None):
    """Segundo inicial (?start=) para sessões HLS/DASH; 0 = do começo. Limitado a duration - 1 quando a duração é conhecida."""
    t = request.args.get("start", type=float)
    start = int(t) if t and math.isfinite(t) and t > 0 else 0  # ?start=1e999 não pode dar 500
    dur = (info or {}).get("duration")
    if start and dur:
        start = min(start, max(int(dur) - 1, 0))
    return start


QUALITIES = {"1080p": (1080, "8000k"), "720p": (720, "4000k"), "480p": (480, "1500k")}


def quality_arg(info=None):
    """Qualidade pedida em ?quality= (1080p/720p/480p); None/original = sem recodificar para bitrate. 400 se inválida.
    Qualidade igual ou acima da altura do vídeo é ignorada (sem upscale), como em `qualities_for`."""
    q = request.args.get("quality")
    if not q or q == "original":
        return None
    if q not in QUALITIES:
        abort(400)
    h = ((info or {}).get("video") or {}).get("height")
    if h and QUALITIES[q][0] >= h:
        return None
    return q


def qualities_for(info):
    h = ((info or {}).get("video") or {}).get("height")
    return ["original"] + [q for q, (qh, _) in QUALITIES.items() if not h or qh < h]


def quality_info(info):
    """55.6: qualidades de `qualities_for` (sem a original) com altura e bitrate (kbps) do servidor."""
    return [{"id": q, "height": QUALITIES[q][0], "kbps": int(QUALITIES[q][1].rstrip("k"))} for q in qualities_for(info) if q in QUALITIES]


def tv_audio_ok(info):
    """TV (ExoPlayer em decodificador de hardware): só toca direto áudio AAC/MP3 em até 2 canais; o resto vai por HLS com áudio AAC estéreo."""
    audio = (info or {}).get("audio") or []
    if not audio:
        return True
    a = audio[0]
    return a.get("codec") in ("aac", "mp3") and (a.get("channels") or 2) <= 2


HDR_MODES = ("auto", "always", "never")


def hdr_mode():
    """50.3: Configurações → Reprodução → HDR (`settings.hdr_mode`): auto (o cliente informa, padrão), always ou never."""
    from server.libraries import get_setting
    try:
        with get_db() as conn:
            v = get_setting(conn, "hdr_mode", "auto")
    except Exception:
        return "auto"
    return v if v in HDR_MODES else "auto"


DIRECT_POLICIES = ("auto", "conservative")


def direct_policy():
    """52.5: Configurações → Reprodução → Direct play (`settings.direct_policy`): auto (usa o `caps` do aparelho, padrão) ou conservative (lista fixa de antes)."""
    from server.libraries import get_setting
    try:
        with get_db() as conn:
            v = get_setting(conn, "direct_policy", "auto")
    except Exception:
        return "auto"
    return v if v in DIRECT_POLICIES else "auto"


def _caps_arg():
    """`caps` do pedido; None com `mode=safe` (52.3) ou com o Direct play Conservador (52.5)."""
    if request.args.get("mode") == "safe" or direct_policy() == "conservative":
        return None
    return parse_caps(request.args)


def hdr_convert(info, client=None):
    """50.3: True se a fonte é HDR e deve virar SDR (sem direct play nem remux). `client` = `hdr=1|0` do cliente; None/0 = converte."""
    if ((info or {}).get("video") or {}).get("hdr", "none") == "none":
        return False
    m = hdr_mode()
    return m == "always" or (m == "auto" and client != "1")


def decide(path, info, audio=None, quality=None, tv=False, hdr_conv=False, caps=None):
    """'direct' (arquivo toca como está), 'remux' (copia vídeo H.264, recodifica áudio) ou 'transcode'."""
    return decide_why(path, info, audio, quality, tv, hdr_conv, caps)[0]


def decide_why(path, info, audio=None, quality=None, tv=False, hdr_conv=False, caps=None):
    """(modo, motivo) — o motivo vai numa linha do log por reprodução (52.1), ex.: `hevc ok, ac3 ok` / `áudio dts`."""
    if info is None or info.get("error") or not info.get("video"):
        return "transcode", "sem análise do arquivo"
    if quality:
        return "transcode", "qualidade " + quality
    if hdr_conv:  # 50.3: HDR em tela SDR cai em transcode (com tone-map, 50.2)
        return "transcode", "HDR para SDR"
    tracks = info.get("audio") or []
    other_audio = audio is not None and tracks and audio != tracks[0]["index"]
    ok, why = _direct_why(path, info, caps)
    if other_audio:
        why = "faixa de áudio escolhida"
    elif ok and caps is None and tv and not tv_audio_ok(info):  # com `caps` quem manda é o perfil do aparelho (52.4)
        ok, why = False, "TV: áudio " + str((tracks[0] if tracks else {}).get("codec"))
    if not other_audio and ok:
        return "direct", why
    if _can_copy_video(info["video"], caps):
        return "remux", why
    return "transcode", why


COPY_VIDEO = ("h264", "hevc", "av1", "vp9")  # 52.2: copiáveis no HLS/DASH (só h264 em TS; os demais em fMP4)
COPY_AUDIO = ("aac", "ac3", "eac3")  # 52.2: áudio que pode ir sem recodificar


def _can_copy_video(v, caps=None):
    """52.2: True se o vídeo pode ser copiado (`-c:v copy`) no HLS/DASH. Sem `caps` = só H.264 8 bits, como antes."""
    c = (v or {}).get("codec")
    if caps is None:
        return c == "h264" and not is_bad_pix(v)
    if c not in COPY_VIDEO or c not in caps.v or _NOT_420.search(v.get("pix_fmt") or ""):
        return False
    if is_10bit(v) and (not caps.b10 or c == "h264"):
        return False
    return v.get("hdr", "none") == "none" or caps.hdr


def _audio_copy(info, audio, caps=None):
    """52.2: True se a faixa escolhida (padrão = 1ª) vai sem recodificar: AAC/AC3/EAC3 listado em `caps.a` e até `caps.ch` canais. Sem `caps` = sempre AAC estéreo."""
    tracks = (info or {}).get("audio") or []
    t = next((x for x in tracks if audio is None or x.get("index") == audio), None)
    return bool(caps and t and t.get("codec") in COPY_AUDIO and t["codec"] in caps.a and (t.get("channels") or 2) <= caps.ch)


def _hls_mode(mode, info, caps=None):
    """Modo do HLS/DASH: vídeo copiável (decisão direct ou remux) é copiado; o resto recodifica."""
    if mode in ("direct", "remux") and _can_copy_video((info or {}).get("video"), caps):
        return "remux"
    return "transcode"


def _no_video(info):
    """True se o ffprobe analisou o arquivo e não achou faixa de vídeo (ex.: só áudio)."""
    return bool(info) and not info.get("error") and not info.get("video")




def get_item(kind, item_id):
    """Devolve (path, info) do filme/episódio se o usuário tiver acesso, senão 404."""
    with get_db() as conn:
        if kind == "movie":
            r = conn.execute("SELECT library_id, path, info FROM media WHERE id = ? AND path IS NOT NULL", (item_id,)).fetchone()
        elif kind == "episode":
            r = conn.execute(
                "SELECT m.library_id, e.path, e.info FROM episodes e JOIN media m ON m.id = e.media_id WHERE e.id = ?",
                (item_id,),
            ).fetchone()
        else:
            r = None
    if not r or not can_access(session["user_id"], r["library_id"]) or not os.path.isfile(r["path"]):
        abort(404)
    return r["path"], (json.loads(r["info"]) if r["info"] else None)


@bp.route("/stream/<kind>/<int:item_id>/direct")
@login_required
def direct(kind, item_id):
    """Direct play com suporte a Range (206)."""
    path, info = get_item(kind, item_id)
    if request.args.get("v") == "opt":  # 52.9: versão otimizada (H.264/AAC em mp4); sumiu ou inválida = 404 e o player volta ao original
        from server import optimize
        out = optimize.find(kind, item_id, path)
        if not out:
            abort(404)
        resp = send_file(out, mimetype="video/mp4", conditional=True, max_age=0)
        resp.headers["Accept-Ranges"] = "bytes"
        return resp
    if info is not None and decide(path, info, audio_arg(info), quality_arg(info), caps=_caps_arg()) != "direct":
        abort(415)
    ext = os.path.splitext(path)[1].lower()
    mime = MIMES.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"
    resp = send_file(path, mimetype=mime, conditional=True, max_age=0)
    resp.headers["Accept-Ranges"] = "bytes"
    return resp


@bp.route("/stream/<kind>/<int:item_id>/info")
@login_required
def stream_info(kind, item_id):
    path, info = get_item(kind, item_id)
    return jsonify(mode=decide(path, info, audio_arg(info), quality_arg(info)), direct=can_direct_play(path, info), qualities=qualities_for(info), quality_info=quality_info(info), info=info)


def _default_audio(info, audio):
    """52.9: True se a faixa pedida é a padrão (1ª); faixa escolhida continua no HLS do original."""
    tracks = (info or {}).get("audio") or []
    return audio is None or not tracks or audio == tracks[0]["index"]


def _optimized_url(kind, item_id, path, caps=None):
    """52.9: URL de direct play da versão otimizada válida (H.264 8 bits + AAC em mp4), ou None.
    Com `caps` que não listam mp4/h264/aac o aparelho não a toca direto: fica o original."""
    if caps and not ({"h264"} <= caps.v and {"mp4"} <= caps.c and {"aac"} <= caps.a):
        return None
    from server import optimize
    return f"/stream/{kind}/{item_id}/direct?v=opt" if optimize.find(kind, item_id, path) else None


@bp.route("/stream/<kind>/<int:item_id>/play", methods=["POST"])
@login_required
def play(kind, item_id):
    """Decide o modo e devolve a URL a tocar: direct play, ou HLS (remux/transcode)."""
    path, info = get_item(kind, item_id)
    if _no_video(info):
        return jerr("err.arquivo_sem_video", 415)
    audio = audio_arg(info)
    quality = quality_arg(info)
    from server import devices  # import tardio (52.6): lembra o aparelho e o `caps` que ele informou
    devices.touch(parse_caps(request.args))
    safe = request.args.get("mode") == "safe"  # 52.3: direct/remux falhou no cliente: transcode completo, sem `caps`
    caps = _caps_arg()
    client_hdr = ("1" if caps.hdr else "0") if caps else request.args.get("hdr")  # 52.1: caps.hdr substitui o hdr= da 50.3
    tv = request.args.get("tv") == "1"
    mode, why = decide_why(path, info, audio, quality, tv=tv, hdr_conv=hdr_convert(info, client_hdr), caps=caps)
    if safe:
        mode, why = "transcode", "modo seguro"
    opt = None
    if mode != "direct" and not safe and request.args.get("mode") != "hls" and not quality and _default_audio(info, audio):
        opt = _optimized_url(kind, item_id, path, caps)  # 52.9: o original não tocaria direto aqui; a otimizada (se houver) toca
        if opt:
            mode, why = "direct", f"versão otimizada (original: {mode}: {why})"
    print(f"[play] {kind} {item_id}: {mode}: {why}", flush=True)
    if mode == "direct" and request.args.get("mode") == "hls":  # o player falhou no direct play: força HLS
        mode = _hls_mode(mode, info, caps)
    if mode == "direct":
        if opt:
            return jsonify(mode=mode, url=opt, offset=0, optimized=True, container="mp4")  # 62.7: a Roku precisa do formato (a URL não tem extensão)
        return jsonify(mode=mode, url=f"/stream/{kind}/{item_id}/direct" + (f"?{caps.param()}" if caps else ""), offset=0, container=_kind(path))
    return _hls(kind, item_id, path, mode, audio, quality, info=info, caps=caps, tv=tv, hdr=client_hdr)


# ---- HLS (H.264 + AAC) ----
SESSIONS = {}  # sid -> {user_id, key, dir, proc}
_LOCK = threading.Lock()


def _running():
    return sum(1 for s in list(SESSIONS.values()) if s["proc"].poll() is None)


def _alive(sess):
    return sess["proc"].poll() is None or os.path.exists(os.path.join(sess["dir"], sess["playlist"]))


_READRATE = None


def has_readrate():
    """True se o ffmpeg conhece `-readrate` (ffmpeg >= 5.0; o 4.4 do Ubuntu 22.04 recusa a opção e todo HLS falha)."""
    global _READRATE
    if _READRATE is None:
        try:
            out = subprocess.run(["ffmpeg", "-hide_banner", "-h", "long"], capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            return False  # ffmpeg ausente/lento: não guarda; start_hls trata o erro real
        _READRATE = "-readrate" in out.stdout
        _BURST[0] = "-readrate_initial_burst" in out.stdout
    return _READRATE


_TONEMAP = [False, None]  # [já detectado, "tonemapx" | "zscale" | None]


def has_tonemap():
    """50.2: filtro de tone-mapping em CPU disponível no ffmpeg: `tonemapx` (>= 7.0), senão `zscale`+`tonemap` (libzimg), senão None.
    Detectado uma vez em `ffmpeg -filters` (se o ffmpeg faltar, não guarda)."""
    if not _TONEMAP[0]:
        try:
            out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            return None
        names = {ln.split()[1] for ln in out.stdout.splitlines() if len(ln.split()) > 2}
        _TONEMAP[1] = "tonemapx" if "tonemapx" in names else "zscale" if {"zscale", "tonemap"} <= names else None
        _TONEMAP[0] = True
    return _TONEMAP[1]


def _hdr_max_height():
    from server.libraries import get_setting
    try:
        with get_db() as conn:
            return max(240, int(get_setting(conn, "hdr_max_height", 1080)))
    except (TypeError, ValueError, Exception):
        return 1080


def tonemap_chain(info, quality=None, max_height=1080):
    """50.2: cadeia `-vf` (escala ANTES do tone-map, teto `max_height`) para fonte HDR; None se a fonte não é HDR ou o ffmpeg não tem filtro."""
    v = (info or {}).get("video") or {}
    hdr = v.get("hdr")
    tool = has_tonemap()
    if not tool or hdr not in ("hdr10", "hlg", "dv5", "dv8"):
        return None
    h = QUALITIES[quality][0] if quality else None
    src = v.get("height") or 0
    if src > max_height:
        h = min(h, max_height) if h else max_height
    chain = [f"scale=-2:{h}"] if h else []
    hlg = hdr == "hlg" or (v.get("color_transfer") or "").lower() == "arib-std-b67"
    if tool == "tonemapx":
        chain.append("tonemapx=tonemap=hable:desat=0:p=bt709:t=bt709:m=bt709:r=tv:format=yuv420p")
    else:
        chain += [f"zscale={'tin=arib-std-b67:' if hlg else ''}t=linear:npl=100", "format=gbrpf32le", "zscale=p=bt709",
                  "tonemap=tonemap=hable:desat=0", "zscale=t=bt709:m=bt709:r=tv", "format=yuv420p"]
    return ",".join(chain)


_BURST = [False]  # ffmpeg >= 7.1: `-readrate_initial_burst` (42.4)


def start_hls(path, out_dir, mode="transcode", audio=None, quality=None, fmt="hls", start=0, info=None, acopy=False, fmp4=False):
    os.makedirs(out_dir, exist_ok=True)
    cmd = [
        "ffmpeg", "-nostdin", "-v", "error", *(["-ss", str(start)] if start else []),
        *(["-readrate", "4", *(["-readrate_initial_burst", "90"] if _BURST[0] else [])] if has_readrate() else []), "-i", path,
        "-map", "0:v:0", "-map", f"0:{audio}" if audio is not None else "0:a:0?", "-sn",
    ]
    if mode == "remux":
        cmd += ["-c:v", "copy"]
        if ((info or {}).get("video") or {}).get("codec") == "hevc":
            cmd += ["-tag:v", "hvc1"]  # 52.2: Apple/ExoPlayer exigem hvc1 em fMP4
    else:
        cmd += [
            "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
            "-sc_threshold", "0", "-force_key_frames", "expr:gte(t,n_forced*6)",
        ]
        tm = tonemap_chain(info, quality, _hdr_max_height())  # 50.2: só transcode e só fonte HDR
        if tm:
            cmd += ["-vf", tm, "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
        if quality:
            height, rate = QUALITIES[quality]
            cmd += (["-vf", f"scale=-2:{height}"] if not tm else []) + ["-b:v", rate, "-maxrate", rate, "-bufsize", f"{int(rate[:-1]) * 2}k"]
    cmd += ["-c:a", "copy"] if acopy else ["-c:a", "aac", "-ac", "2", "-b:a", "160k"]  # 52.2: AC3/EAC3/AAC sem recodificar só com `caps`
    if fmt == "dash":
        cmd += [
            "-f", "dash", "-seg_duration", "6", "-use_template", "1", "-use_timeline", "1",
            "-init_seg_name", "init-$RepresentationID$.m4s",
            "-media_seg_name", "chunk-$RepresentationID$-$Number%05d$.m4s",
            os.path.join(out_dir, "index.mpd"),
        ]
    else:
        cmd += [
            "-f", "hls", "-hls_time", "6", "-hls_list_size", "0", "-hls_playlist_type", "event",
            *(["-hls_segment_type", "fmp4", "-hls_fmp4_init_filename", "init.mp4"] if fmp4 else []),
            "-hls_segment_filename", os.path.join(out_dir, "seg%05d.m4s" if fmp4 else "seg%05d.ts"),
            os.path.join(out_dir, "index.m3u8"),
        ]
    with open(os.path.join(out_dir, "ffmpeg.log"), "wb") as log:  # o motivo da falha fica no log (antes ia para o lixo)
        if mode != "remux" and tonemap_chain(info, quality, _hdr_max_height()):
            log.write(f"[starflix] tone-map HDR->SDR ({has_tonemap()}, {info['video'].get('hdr')})\n".encode())
            log.flush()
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=log)


def _log_tail(sess, n=400):
    try:
        with open(os.path.join(sess["dir"], "ffmpeg.log"), "rb") as fh:
            return fh.read()[-n:].decode("utf-8", "replace").strip()
    except OSError:
        return ""


@bp.route("/stream/<kind>/<int:item_id>/hls", methods=["POST"])
@login_required
def hls_start(kind, item_id):
    """Inicia (ou reaproveita) uma sessão HLS e devolve a URL do playlist."""
    path, info = get_item(kind, item_id)
    if _no_video(info):
        return jerr("err.arquivo_sem_video", 415)
    audio, quality, caps = audio_arg(info), quality_arg(info), _caps_arg()
    client_hdr = ("1" if caps.hdr else "0") if caps else request.args.get("hdr")
    mode = _hls_mode(decide(path, info, audio, quality, hdr_conv=hdr_convert(info, client_hdr), caps=caps), info, caps)
    return _hls(kind, item_id, path, mode, audio, quality, info=info, caps=caps, hdr=client_hdr)


@bp.route("/stream/<kind>/<int:item_id>/dash", methods=["POST"])
@login_required
def dash_start(kind, item_id):
    """Mesmo fluxo do HLS, com saída DASH (.mpd)."""
    path, info = get_item(kind, item_id)
    if _no_video(info):
        return jerr("err.arquivo_sem_video", 415)
    audio, quality, caps = audio_arg(info), quality_arg(info), _caps_arg()
    client_hdr = ("1" if caps.hdr else "0") if caps else request.args.get("hdr")
    mode = _hls_mode(decide(path, info, audio, quality, hdr_conv=hdr_convert(info, client_hdr), caps=caps), info, caps)
    return _hls(kind, item_id, path, mode, audio, quality, "dash", info, caps)


WARM_TTL = 300  # 52.12: sessão aquecida que ninguém reclama é encerrada em 5 min


def _hls(kind, item_id, path, mode, audio=None, quality=None, fmt="hls", info=None, caps=None, tv=False, hdr=None, warm=False, uid=None):
    """`warm=True` (52.12): só cria a sessão do próximo episódio (sem esperar o playlist, nunca expulsa outra sessão) e devolve o sid ou None."""
    start = 0 if warm else start_arg(info)
    if mode == "remux" and start > 0:
        mode = "transcode"  # -ss com -c:v copy começa no keyframe e dessincroniza o offset (52.2: seek em remux não medido, regra mantida)
    acopy = _audio_copy(info, audio, caps)
    fmp4 = mode == "remux" and ((info or {}).get("video") or {}).get("codec") != "h264"  # hevc/av1/vp9 só em fMP4
    tm = has_tonemap() if mode != "remux" and ((info or {}).get("video") or {}).get("hdr", "none") != "none" else None
    key = (kind, item_id, mode, audio, quality, fmt, start, tm, "copy" if acopy else "aac", fmp4)  # 50.2: HDR (tone-map) e SDR do mesmo arquivo não se misturam
    playlist_name = "index.mpd" if fmt == "dash" else "index.m3u8"
    uid = session["user_id"] if uid is None else uid
    with _LOCK:  # busca/limite/criação/registro atômicos (duplo clique, 2 abas, retry)
        sid = next((i for i, s in list(SESSIONS.items())
                    if s["user_id"] == uid and s["key"] == key and _alive(s)), None)
        if sid is not None and warm:
            return sid
        if sid is not None and SESSIONS[sid].pop("warm", None):  # 52.12: o /play do próximo episódio reclamou a sessão aquecida
            SESSIONS[sid]["last"] = time.time()
        if sid is None:
            if warm:  # aquecer nunca expulsa ninguém: sem vaga, sem disco ou com outra sessão aquecida do usuário, não faz nada
                if config.MAX_TRANSCODES > 0 and _running() >= config.MAX_TRANSCODES:
                    return None
                if any(x["user_id"] == uid and x.get("warm") for x in list(SESSIONS.values())):
                    return None
            elif config.MAX_TRANSCODES > 0 and _running() >= config.MAX_TRANSCODES:
                for old_sid, s in list(SESSIONS.items()):  # libera as sessões ativas do próprio usuário (troca de áudio/qualidade)
                    if s["user_id"] == uid and s["proc"].poll() is None:
                        _drop(old_sid)
                if _running() >= config.MAX_TRANSCODES:
                    return jerr("err.servidor_ocupado_limite_transcodes_simultaneos", 503)
            if config.MIN_FREE_GB > 0:
                os.makedirs(config.TRANSCODE_DIR, exist_ok=True)
                if shutil.disk_usage(config.TRANSCODE_DIR).free < config.MIN_FREE_GB * 1024 ** 3:
                    if warm:
                        return None
                    return jerr("err.espaco_disco_insuficiente_transcodificar", 503)
            sid = secrets.token_hex(8)
            out_dir = os.path.join(config.TRANSCODE_DIR, sid)
            try:
                proc = start_hls(path, out_dir, mode, audio, quality, fmt, start, info, acopy, fmp4)
            except FileNotFoundError:
                shutil.rmtree(out_dir, ignore_errors=True)
                if warm:
                    return None
                return jerr("err.ffmpeg_nao_instalado", 500)
            if mode == "transcode":
                try:
                    from server import optimize  # 52.8: reprodução com transcode tem prioridade sobre a otimização
                    optimize.pause_for_play()
                except Exception:  # noqa: BLE001
                    pass
            SESSIONS[sid] = {"user_id": uid, "key": key, "dir": out_dir, "proc": proc, "started": time.time(), "playlist": playlist_name,
                             "caps": caps, "tv": bool(tv), "hdr": hdr}  # 52.12: o aparelho que pediu (para aquecer o próximo com o mesmo perfil)
            if warm:
                SESSIONS[sid]["warm"] = True
        sess = SESSIONS[sid]
    if warm:
        return sid
    playlist = os.path.join(sess["dir"], playlist_name)
    for _ in range(360):  # espera o playlist (até 90 s: vídeo pesado recodificado em CPU demora a gerar o 1º trecho), fora da trava, também ao reaproveitar a sessão
        if os.path.exists(playlist):
            return jsonify(mode=mode, url=f"/stream/{fmt}/{sid}/{playlist_name}", offset=start, sid=sid, hdr_sdr=bool(tm), dv5=bool(tm) and info["video"].get("hdr") == "dv5")  # 50.4
        if sess["proc"].poll() is not None:
            break
        time.sleep(0.25)
    detail = _log_tail(sess) or ("ffmpeg ainda não gerou o playlist em 90 s" if sess["proc"].poll() is None else "")
    if detail:
        print(f"[stream] falha ao iniciar {kind} {item_id} ({mode}): {detail}", flush=True)
    _drop(sid)  # mata, aguarda (sem zumbi) e apaga a pasta
    return jerr("err.falha_iniciar_transcode", 500, detail=detail)


def _playlist_with_token(fpath, it):
    """62.16: reescreve as URIs relativas do .m3u8 (linhas de segmento e URI="..." de EXT-X-MAP/KEY) acrescentando `it=<token>`."""
    def add(u):
        if u.startswith(("http://", "https://")) or "it=" in u:
            return u
        return u + ("&" if "?" in u else "?") + "it=" + quote(it, safe="")
    out = []
    with open(fpath, encoding="utf-8") as fh:
        for line in fh.read().splitlines():
            if not line.strip():
                out.append(line)
            elif line.startswith("#"):
                out.append(re.sub(r'URI="([^"]+)"', lambda m: 'URI="' + add(m.group(1)) + '"', line))
            else:
                out.append(add(line.strip()))
    r = Response("\n".join(out) + "\n")
    r.headers["Cache-Control"] = "no-cache"
    return r


@bp.route("/stream/hls/<sid>/<name>")
@bp.route("/stream/dash/<sid>/<name>")
@login_required
def hls_file(sid, name):
    s = SESSIONS.get(sid)
    if not s or s["user_id"] != session["user_id"]:
        abort(404)
    s["last"] = time.time()
    resp = send_from_directory(s["dir"], name, max_age=0)
    it = request.args.get("it")
    if it and name.endswith(".m3u8"):  # 62.16: segmentos/init são relativos e perderiam o ?it=; propaga o token no playlist
        resp = _playlist_with_token(os.path.join(s["dir"], name), it)
    if name.endswith(".m3u8"):
        resp.mimetype = "application/vnd.apple.mpegurl"
    elif name.endswith(".ts"):
        resp.mimetype = "video/mp2t"
    elif name.endswith(".mpd"):
        resp.mimetype = "application/dash+xml"
    elif name.endswith(".m4s"):
        resp.mimetype = "video/iso.segment"
    elif name.endswith(".mp4"):
        resp.mimetype = "video/mp4"  # init.mp4 do fMP4 (52.2)
    return resp


# ---- limpeza de sessões antigas ----
def _drop(sid):
    s = SESSIONS.pop(sid, None)
    if not s:
        return
    if s["proc"].poll() is None:
        s["proc"].kill()
        s["proc"].wait()
    shutil.rmtree(s["dir"], ignore_errors=True)


WARM_LEFT = 90  # s restantes (ou >= 95 %) para aquecer o próximo episódio


def warm_next(uid, ep_id, pos, duration):
    """52.12: chamado a cada salvamento de progresso (~10 s). Faltando <= 90 s (ou >= 95 %) de um episódio em HLS, com áudio padrão, inicia a sessão do próximo
    com o modo/qualidade que o decide() escolheria para o mesmo aparelho (mesma chave que o /play dele vai pedir). Nunca expulsa sessão alheia; qualquer falha é engolida."""
    try:
        if not duration or duration <= 0 or (duration - pos > WARM_LEFT and pos / duration < 0.95):
            return None
        cur = max((x for x in list(SESSIONS.values()) if x["user_id"] == uid and x["key"][0] == "episode" and x["key"][1] == ep_id and x["key"][5] == "hls"
                   and "caps" in x and not x.get("warm") and _alive(x)), key=lambda x: x["started"], default=None)
        if cur is None or cur["key"][3] is not None:  # sem sessão HLS (direct play) ou áudio escolhido: nada a aquecer
            return None
        from server.progress import next_episode  # import tardio: progress importa stream
        n = next_episode(ep_id)
        if not n:
            return None
        path, info = get_item("episode", n["id"])
        if _no_video(info):
            return None
        quality, caps = cur["key"][4], cur["caps"]
        mode = decide(path, info, None, quality, tv=cur["tv"], hdr_conv=hdr_convert(info, cur["hdr"]), caps=caps)
        if mode == "direct":
            return None
        from server import optimize
        if not quality and optimize.find("episode", n["id"], path):  # a otimizada toca direto: não há o que aquecer
            return None
        return _hls("episode", n["id"], path, mode, None, quality, info=info, caps=caps, tv=cur["tv"], hdr=cur["hdr"], warm=True, uid=uid)
    except Exception as e:  # noqa: BLE001 - falhar aqui nunca atrapalha o episódio em curso
        print(f"[warm] {e}", flush=True)
        return None


def cleanup_sessions(ttl=None):
    """Encerra o ffmpeg e apaga os arquivos das sessões sem atividade há mais de `ttl` segundos."""
    ttl = config.TRANSCODE_TTL if ttl is None else ttl
    now = time.time()
    for sid, s in list(SESSIONS.items()):
        if now - s.get("last", s["started"]) > ttl or (s.get("warm") and now - s["started"] > WARM_TTL):  # 52.12: aquecida sem dono expira
            _drop(sid)


def clean_orphans():
    """Apaga pastas de transcode que sobraram de execuções anteriores (sem sessão ativa)."""
    for d in os.listdir(config.TRANSCODE_DIR):
        full = os.path.join(config.TRANSCODE_DIR, d)
        if os.path.isdir(full) and d not in SESSIONS:
            shutil.rmtree(full, ignore_errors=True)


def _clean_subs():
    from server.subtitles import clean_subs  # import tardio: subtitles importa stream
    try:
        clean_subs()
    except Exception:
        pass


def _refresh_tmdb_lists():
    from server import tmdb_lists  # import tardio
    try:
        tmdb_lists.refresh_stale()
    except Exception:
        pass


def _clean_tv_codes():
    """40.1: códigos de pareamento da TV vencidos."""
    try:
        from server.db import clean_tv_codes, get_db
        with get_db() as conn:
            clean_tv_codes(conn)
    except Exception:
        pass


def start_cleanup(interval=None):
    interval = config.TRANSCODE_CLEAN_INTERVAL if interval is None else interval
    clean_orphans()
    _clean_subs()
    _clean_tv_codes()
    threading.Thread(target=_refresh_tmdb_lists, daemon=True).start()  # 32.2: listas do TMDB (sem travar a subida)
    from server import backup
    threading.Thread(target=backup.maybe_backup, daemon=True).start()  # 51.2: backup vencido (ex.: servidor ficou desligado)
    if interval <= 0:
        return

    def loop():
        last_subs = last_lists = last_backup = time.time()
        while True:
            time.sleep(interval)
            try:
                cleanup_sessions()
            except Exception:
                pass
            try:
                from server import optimize
                optimize.tick()  # 52.8: versão otimizada na janela de horário
            except Exception as e:  # noqa: BLE001
                print(f"[optimize] {e}", flush=True)
            if time.time() - last_subs >= 3600:  # cache de legendas: uma vez por hora
                last_subs = time.time()
                _clean_subs()
                _clean_tv_codes()
            if time.time() - last_lists >= 3600:  # TMDB: confere de hora em hora, renova só o que passou de 24 h
                last_lists = time.time()
                _refresh_tmdb_lists()
            if time.time() - last_backup >= 3600:  # 51.2: backup a cada `backup_days` (confere de hora em hora)
                last_backup = time.time()
                backup.maybe_backup()

    threading.Thread(target=loop, daemon=True).start()


@bp.route("/stream/session/<sid>/stop", methods=["POST"])
@login_required
def stop_session(sid):
    """Encerra uma sessão de transcode (o player chama ao trocar áudio/qualidade/posição)."""
    s = SESSIONS.get(sid)
    if s and s["user_id"] == session["user_id"]:
        _drop(sid)
    return jsonify(ok=True)


@bp.route("/download/movie/<int:item_id>")
@login_required
def download_movie(item_id):
    """Salvar arquivo (25.7): baixa o arquivo original do filme (attachment, com Range). Só com acesso à biblioteca;
    o caminho precisa estar dentro da pasta da biblioteca e ser um arquivo de vídeo."""
    with get_db() as conn:
        r = conn.execute("SELECT library_id, path FROM media WHERE id = ? AND path IS NOT NULL", (item_id,)).fetchone()
        roots = library_folders(conn, r["library_id"]) if r else []
    if not r or not can_access(session["user_id"], r["library_id"]):
        abort(404)
    path = os.path.abspath(r["path"])
    ext = os.path.splitext(path)[1].lower()
    if (not any(path == os.path.abspath(f) or path.startswith(os.path.abspath(f).rstrip(os.sep) + os.sep) for f in roots)
            or ext not in {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".wmv", ".ts", ".flv", ".mpg", ".mpeg"}
            or not os.path.isfile(path)):
        abort(404)
    mime = MIMES.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"
    resp = send_file(path, mimetype=mime, as_attachment=True, download_name=os.path.basename(path), conditional=True, max_age=0)
    resp.headers["Accept-Ranges"] = "bytes"
    return resp
