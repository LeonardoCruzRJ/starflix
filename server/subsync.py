"""64.18 a 64.20: sincronia automática de legenda. Aqui: mapa de fala do vídeo (quadros de 100 ms com voz), em CPU e sem dependência nova."""
import json
import logging
import math
import os
import shutil
import subprocess
import tempfile

import config
from server.db import get_db

log = logging.getLogger("starflix.subsync")

FRAME = 0.1            # s por quadro
CHUNK = 6000           # quadros por inteiro (10 min): o mapa é uma lista de inteiros, um por trecho
AVG_FRAMES = 300       # janela da média móvel (30 s) que serve de limiar
MARGIN_DB = 3.0        # voz = acima da média móvel + 3 dB
FLOOR_DB = -55.0       # abaixo disso é silêncio, qualquer que seja a média
VERSION = 1            # sobe se o critério mudar (invalida o cache)
_KINDS = ("movie", "episode")


def _nice(cmd):
    """CPU e disco no mínimo (nice 19 + ionice ocioso), igual a markers.py."""
    pre = ["ionice", "-c3"] if shutil.which("ionice") else []
    return pre + (["nice", "-n", "19"] if shutil.which("nice") else []) + cmd


def _cache_path(kind, item_id):
    return os.path.join(config.SUBSYNC_DIR, f"{kind}_{int(item_id)}.json")


def _levels(path, track):
    """Nível RMS (dB) de cada quadro de 100 ms da faixa `track`, de 300 a 3400 Hz, mono 8 kHz; None se o ffmpeg falhar."""
    if not shutil.which("ffmpeg"):
        return None
    af = ("aformat=channel_layouts=mono,aresample=8000,highpass=f=300,lowpass=f=3400,asetnsamples=n=800:p=0,"
          "astats=metadata=1:reset=1,ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-")
    cmd = _nice(["ffmpeg", "-nostdin", "-threads", "1", "-v", "error", "-i", path, "-map", f"0:a:{int(track)}", "-vn", "-sn",
                 "-ac", "1", "-ar", "8000", "-af", af, "-f", "null", "-"])
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL)
    except OSError:
        return None
    waited = 0.0
    while True:  # 64.23: a fila noturna pode ser interrompida (transcode, reprodução, fim da janela): mata o ffmpeg
        try:
            stdout, _ = p.communicate(timeout=2)
            break
        except subprocess.TimeoutExpired:
            waited += 2
            if _ABORT.is_set() or waited > 3 * 3600:
                p.kill()
                p.communicate()
                return None
    if p.returncode != 0:
        return None
    out = []
    for line in stdout.splitlines():
        if line.startswith("lavfi.astats.Overall.RMS_level="):
            v = line.split("=", 1)[1].strip()
            try:
                out.append(max(float(v), -120.0))  # "-inf" (silêncio digital) cai no except abaixo
            except ValueError:
                out.append(-120.0)
    return out or None


def speech_frames(levels):
    """Lista de bool (1 por quadro): voz quando o nível passa da média móvel do próprio vídeo + margem e do piso."""
    n = len(levels)
    pre = [0.0]
    for v in levels:
        pre.append(pre[-1] + v)
    half = AVG_FRAMES // 2
    out = []
    for i, v in enumerate(levels):
        a, b = max(0, i - half), min(n, i + half + 1)
        avg = (pre[b] - pre[a]) / (b - a)
        out.append(v > FLOOR_DB and v > avg + MARGIN_DB)
    return out


def pack(frames):
    """Quadros -> lista de inteiros (um por trecho de CHUNK quadros; o bit i do inteiro é o quadro i do trecho)."""
    out = []
    for s in range(0, len(frames), CHUNK):
        v = 0
        for i, f in enumerate(frames[s:s + CHUNK]):
            if f:
                v |= 1 << i
        out.append(v)
    return out


def unpack(chunks, n):
    """Inverso de pack: n quadros em bool."""
    return [bool((chunks[i // CHUNK] >> (i % CHUNK)) & 1) for i in range(n)]


def video_map(kind, item_id, path, track=0):
    """{'frames': n, 'chunks': [int, ...]} do vídeo (cache em data/subsync/); None se não der para extrair o áudio."""
    if kind not in _KINDS:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = {"v": VERSION, "size": st.st_size, "mtime": int(st.st_mtime), "track": int(track)}
    cp = _cache_path(kind, item_id)
    try:
        with open(cp, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("key") == key:
            return {"frames": d["frames"], "chunks": [int(x, 16) for x in d["chunks"]]}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    lv = _levels(path, track)
    if not lv:
        return None
    frames = speech_frames(lv)
    chunks = pack(frames)
    os.makedirs(config.SUBSYNC_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=config.SUBSYNC_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"key": key, "frames": len(frames), "chunks": [format(c, "x") for c in chunks]}, f)
        os.replace(tmp, cp)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return {"frames": len(frames), "chunks": chunks}


def prune():
    """Apaga o cache de vídeos que saíram do banco (chamado por scanner.prune_missing)."""
    if not os.path.isdir(config.SUBSYNC_DIR):
        return
    with get_db() as conn:
        have = {"movie": {r[0] for r in conn.execute("SELECT id FROM media WHERE path IS NOT NULL")},
                "episode": {r[0] for r in conn.execute("SELECT id FROM episodes")}}
    for f in os.listdir(config.SUBSYNC_DIR):
        p = os.path.join(config.SUBSYNC_DIR, f)
        base, ext = os.path.splitext(f)
        kind, _, num = base.partition("_")
        keep = ext == ".json" and kind in have and num.isdigit() and int(num) in have[kind]
        if not keep:
            try:
                os.remove(p)
            except OSError:
                pass


# ---- 64.19: mapa de fala da legenda --------------------------------------------------------------------------------------------
import re  # noqa: E402

_TS = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})\s*-->\s*(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})")
_TAGS = re.compile(r"<[^>]*>|\{\\[^}]*\}")
_EFFECT = re.compile(r"^\s*[\[\(（【♪♫#*].*[\]\)）】♪♫#*]?\s*$")  # [música], (risos), ♪ letra ♪ (só efeito/canto), linha inteira entre colchetes
_ONLY_SYMBOLS = re.compile(r"^[\W_]*$", re.U)
_FORCED = re.compile(r"forced|for[cç]ad|forzad|forc[eé]e?s?\b|erzwungen|forzat|принудит|zorunlu|強制|强制|僅|仅", re.I)  # i18n-ok: nomes de "forçada" nos 10 idiomas para reconhecer a faixa, não aparece na interface
MIN_REF_CUES = 40      # faixa com menos falas que isso é "forçada" mesmo sem o nome (só traduz trechos estrangeiros)


def _t(h, m, s, ms):
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_cues(text):
    """[(início, fim, texto)] de um .srt ou .vtt (ordem do arquivo; cue ilegível é ignorado)."""
    cues = []
    for block in re.split(r"\n\s*\n", (text or "").lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")):
        lines = block.split("\n")
        i = next((n for n, l in enumerate(lines) if "-->" in l), None)
        if i is None:
            continue
        m = _TS.search(lines[i])
        if not m:
            continue
        s, e = _t(*m.group(1, 2, 3, 4)), _t(*m.group(5, 6, 7, 8))
        if e > s:
            cues.append((s, e, "\n".join(lines[i + 1:])))
    return cues


def spoken(text):
    """True se a fala escrita é diálogo: sem tags, sem linha só de efeito ([música], (risos), ♪…♪) nem só de símbolos."""
    kept = []
    for ln in _TAGS.sub("", text or "").split("\n"):
        ln = ln.strip()
        if not ln or _ONLY_SYMBOLS.match(ln) or _EFFECT.match(ln):
            continue
        kept.append(ln)
    return bool(kept)


def sub_map(cues):
    """Mapa de fala de uma legenda: {'frames': n, 'chunks': [...]} no mesmo formato de video_map (quadros de 100 ms com fala escrita)."""
    cues = [(s, e) for s, e, t in cues if spoken(t)]
    if not cues:
        return None
    n = int(max(e for _, e in cues) / FRAME) + 1
    frames = [False] * n
    for s, e in cues:
        for i in range(max(0, int(s / FRAME)), min(n, int(e / FRAME) + 1)):
            frames[i] = True
    return {"frames": n, "chunks": pack(frames)}


def subtitle_map(text):
    """Mapa de fala a partir do texto de um .srt/.vtt; None se não houver fala."""
    return sub_map(parse_cues(text))


def reference_track(info, lang=None, exclude_index=None):
    """Faixa de legenda de texto embutida para servir de referência no lugar do áudio: outro idioma que o da legenda a sincronizar,
    sem faixa 'forçada' (pelo nome). Devolve o dict da faixa ou None. Preferência: a 1ª na ordem do arquivo."""
    from server.subtitles import embedded_subs
    lang = (lang or "").lower()[:2]
    for t in embedded_subs(info):
        if exclude_index is not None and t.get("index") == exclude_index:
            continue
        if _FORCED.search(t.get("title") or ""):
            continue
        if lang and (t.get("lang") or "").lower()[:2] == lang:
            continue  # mesmo idioma não serve: o texto da referência pode ser a própria legenda
        return t
    return None


def reference_map(video_path, info, lang=None, exclude_index=None):
    """Mapa de fala da legenda embutida de referência (mais exato e bem mais barato que o áudio); None se não houver ou for forçada."""
    from server.subtitles import extract_vtt, _read
    t = reference_track(info, lang, exclude_index)
    if not t:
        return None
    vtt = extract_vtt(video_path, t["index"])
    if not vtt:
        return None
    cues = parse_cues(_read(vtt))
    if sum(1 for _, _, x in cues if spoken(x)) < MIN_REF_CUES:
        return None  # poucas falas = forçada
    return sub_map(cues)


# ---- 64.20: correlação ---------------------------------------------------------------------------------------------------------
import threading  # noqa: E402

from flask import Blueprint, jsonify, request  # noqa: E402

from server.auth import login_required  # noqa: E402

bp = Blueprint("subsync", __name__)

SEARCH = 1200                  # ±120 s em quadros
WIN = 6000                     # ~10 min por janela
MIN_WIN = 1200                 # janela mínima (2 min) em vídeos curtos
MIN_SPEECH = 150               # quadros com fala (15 s) para a janela contar
AGREE = 5                      # janelas concordam em até 0,5 s (5 quadros)
Z_OK = 5.0                     # o pico precisa se destacar do ruído em 5 desvios
MAX_DURATION = 4 * 3600        # vídeos maiores que 4 h não são sincronizados
RATES = (1.0, 24 / 23.976, 23.976 / 24, 25 / 23.976, 23.976 / 25, 25 / 24, 24 / 25)  # 1,0 e as razões usuais
CONF_AUTO = 0.6                # 64.21: confiança a partir da qual o resultado é gravado sozinho
_LOCK = threading.Lock()       # uma sincronização por vez (o áudio pesa na CPU)
_ABORT = threading.Event()     # 64.23: pede para a fila noturna parar (ffmpeg é morto, nada é gravado nem marcado)


def _bits(m):
    """Mapa -> um inteiro só (bit i = quadro i)."""
    v = 0
    for k, c in enumerate(m["chunks"]):
        v |= c << (k * CHUNK)
    return v


def _setframes(m):
    out, n = [], m["frames"]
    for k, c in enumerate(m["chunks"]):
        base = k * CHUNK
        while c:
            low = c & -c
            j = base + low.bit_length() - 1
            if j < n:
                out.append(j)
            c ^= low
    return out


def _pop(x):
    return x.bit_count() if hasattr(x, "bit_count") else bin(x).count("1")


def _search(V, J, a, length, r):
    """Melhor deslocamento d (quadros) de uma janela da legenda [a, a+length) escalada por r sobre o vídeo, d em ±SEARCH.
    Devolve (d, z) ou None: z = quanto o melhor XOR se destaca da média dos demais, em desvios."""
    sel = [j for j in J if a <= j < a + length]
    if len(sel) < MIN_SPEECH:
        return None
    base = int(round(a * r))
    span = int(round((a + length) * r)) - base
    sw = 0
    for j in sel:
        sw |= 1 << (int(round(j * r)) - base)
    mask = (1 << span) - 1
    scores = []
    for d in range(-SEARCH, SEARCH + 1):
        p = base + d
        vw = (V >> p) if p >= 0 else (V << -p)
        scores.append(_pop((vw & mask) ^ sw))
    best = min(range(len(scores)), key=scores.__getitem__)
    rest = [s for i, s in enumerate(scores) if abs(i - best) > 20]
    if not rest:
        return None
    mean = sum(rest) / len(rest)
    sd = (sum((s - mean) ** 2 for s in rest) / len(rest)) ** 0.5 or 1.0
    return best - SEARCH, (mean - scores[best]) / sd


def correlate(vmap, smap):
    """64.20: {offset (s), rate, confidence (0 a 1), windows: [{t, offset, z}]}; offset/rate valem em t' = t·rate + offset (t da legenda)."""
    V, S = _bits(vmap), _setframes(smap)
    total = min(vmap["frames"], smap["frames"])
    length = max(MIN_WIN, min(WIN, total // 4))
    starts = sorted({max(0, min(total - length, int(total * f) - length // 2)) for f in (0.15, 0.5, 0.85)})
    cands = []
    for r in RATES:
        res = [(a, _search(V, S, a, length, r)) for a in starts]
        res = [(a, x) for a, x in res if x]
        if len(res) < 2:
            continue
        ds = [x[0] for _, x in res]
        cand = {"r": r, "agree": max(ds) - min(ds) <= AGREE, "ok": all(x[1] >= Z_OK for _, x in res),
                "z": sum(x[1] for _, x in res), "res": res}
        cand["good"] = cand["agree"] and cand["ok"]
        if r == 1.0 and cand["good"]:
            cands = [cand]  # 1,0 passou: nenhuma outra razão é testada
            break
        cands.append(cand)
    good = [c for c in cands if c["good"]]
    best = max(good or cands, key=lambda c: c["z"], default=None)
    if best is None:
        return {"offset": 0.0, "rate": 1.0, "confidence": 0.0, "windows": []}
    ds = sorted(x[0] for _, x in best["res"])
    off = ds[len(ds) // 2] * FRAME
    zavg = best["z"] / len(best["res"])
    conf = min(1.0, zavg / (2 * Z_OK)) if best["good"] else min(0.4, zavg / (4 * Z_OK))
    return {"offset": round(off, 1), "rate": round(best["r"], 5) if best["r"] != 1.0 else 1.0, "confidence": round(conf, 2),
            "windows": [{"t": round(a * FRAME, 1), "offset": round(x[0] * FRAME, 1), "z": round(x[1], 1)} for a, x in best["res"]]}


def _find_sub(kind, item_id):
    """(chave, texto da legenda, lang, índice embutido|None) conforme o corpo; abort 404 se a chave não existe (igual a subs/offset)."""
    from flask import abort
    from server import subtitles as st
    path, info = st.get_item(kind, item_id)
    data = request.get_json(silent=True)
    key = data.get("key") if isinstance(data, dict) else None
    if not isinstance(key, str):
        abort(404)
    for s in st.external_subs(path):
        if st.ext_key(s) == key:
            return path, info, st._read(s["file"]), s.get("lang"), None
    for t in st.embedded_subs(info):
        if st.emb_key(t) == key:
            vtt = st.extract_vtt(path, t["index"])
            if vtt:
                return path, info, st._read(vtt), t.get("lang"), t["index"]
    abort(404)


@bp.route("/stream/<kind>/<int:item_id>/subs/autosync", methods=["POST"])
@login_required
def autosync(kind, item_id):
    """Calcula o atraso/razão que sincroniza a legenda; confiança alta (>= CONF_AUTO) grava em `sub_offset` com Desfazer (64.21), baixa só sugere. Uma por vez."""
    path, info, text, lang, idx = _find_sub(kind, item_id)
    smap = subtitle_map(text)
    if not smap:
        return jsonify(ok=False, reason="no_speech"), 422
    dur = float((info or {}).get("duration") or 0)
    if dur > MAX_DURATION:
        return jsonify(ok=False, reason="too_long"), 422
    if _BG["thread"] is not None and _BG["thread"].is_alive():
        _ABORT.set()  # 64.23: o pedido do usuário passa na frente da fila noturna
        got = _LOCK.acquire(timeout=10)
    else:
        got = _LOCK.acquire(blocking=False)
    if not got:
        return jsonify(ok=False, reason="busy"), 409
    _ABORT.clear()
    try:
        vmap = reference_map(path, info, lang, idx)
        source = "subtitle"
        if not vmap:
            vmap, source = video_map(kind, item_id, path, 0), "audio"
        if not vmap:
            return jsonify(ok=False, reason="no_audio"), 422
        res = correlate(vmap, smap)
    finally:
        _LOCK.release()
    key = request.get_json(silent=True)["key"]
    out = {"applied": False, "confirm": False}
    if res["confidence"] >= CONF_AUTO and (res["offset"] != 0 or res["rate"] != 1.0):
        with get_db() as conn:
            cur = _row(conn, kind, item_id, key)
            if cur and cur["source"] == "manual" and (cur["offset"] != 0 or cur["rate"] != 1.0):
                out["confirm"] = True  # ajuste do usuário: só troca com confirmação (rota /save)
            else:
                _save(conn, kind, item_id, key, res["offset"], res["rate"])
                out["applied"] = True
    out["undo"] = _undo_ok(kind, item_id, key)
    return jsonify(ok=True, source=source, **res, **out)


def _row(conn, kind, item_id, key):
    return conn.execute("SELECT * FROM sub_offset WHERE item_type = ? AND item_id = ? AND sub_key = ?", (kind, item_id, key)).fetchone()


def _undo_ok(kind, item_id, key):
    with get_db() as conn:
        r = _row(conn, kind, item_id, key)
    return bool(r and r["prev_source"] is not None)


def _save(conn, kind, item_id, key, offset, rate):
    """64.21: grava o resultado do AutoSync em `sub_offset` guardando o valor anterior (Desfazer); sobre um registro `auto`, mantém o anterior mais antigo."""
    from server.subtitles import OFFSET_MAX
    offset = round(max(-OFFSET_MAX, min(OFFSET_MAX, float(offset))), 1)
    cur = _row(conn, kind, item_id, key)
    if cur and cur["source"] == "auto":
        prev = (cur["prev_offset"], cur["prev_rate"], cur["prev_source"])
    elif cur:
        prev = (cur["offset"], cur["rate"], cur["source"])
    else:
        prev = (None, None, "none")
    conn.execute(
        "INSERT INTO sub_offset (item_type, item_id, sub_key, offset, rate, source, prev_offset, prev_rate, prev_source) "
        "VALUES (?, ?, ?, ?, ?, 'auto', ?, ?, ?) ON CONFLICT(item_type, item_id, sub_key) DO UPDATE SET "
        "offset = excluded.offset, rate = excluded.rate, source = 'auto', "
        "prev_offset = excluded.prev_offset, prev_rate = excluded.prev_rate, prev_source = excluded.prev_source",
        (kind, item_id, key, offset, rate, *prev))


def _body_key(kind, item_id):
    from flask import abort
    from server import subtitles as st
    path, info = st.get_item(kind, item_id)
    data = request.get_json(silent=True)
    data = data if isinstance(data, dict) else {}
    key = data.get("key")
    if key not in {st.ext_key(s) for s in st.external_subs(path)} | {st.emb_key(t) for t in st.embedded_subs(info)}:
        abort(404)
    return key, data


@bp.route("/stream/<kind>/<int:item_id>/subs/autosync/save", methods=["POST"])
@login_required
def autosync_save(kind, item_id):
    """64.21: o usuário aceita uma sugestão (confiança baixa ou ajuste manual a trocar): grava `{key, offset, rate}` com Desfazer."""
    from flask import abort
    key, d = _body_key(kind, item_id)
    off, rate = d.get("offset"), d.get("rate", 1.0)
    for v in (off, rate):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            abort(400)
    if not 0.9 <= rate <= 1.1:
        abort(400)
    with get_db() as conn:
        _save(conn, kind, item_id, key, off, rate)
    return jsonify(ok=True, undo=True)


@bp.route("/stream/<kind>/<int:item_id>/subs/autosync/undo", methods=["POST"])
@login_required
def autosync_undo(kind, item_id):
    """64.21: Desfazer: devolve o atraso/razão que valiam antes do AutoSync (sem registro antes = apaga). 409 se não há o que desfazer."""
    key, _ = _body_key(kind, item_id)
    with get_db() as conn:
        r = _row(conn, kind, item_id, key)
        if not r or r["prev_source"] is None:
            return jsonify(ok=False, reason="nothing"), 409
        if r["prev_source"] == "none":
            conn.execute("DELETE FROM sub_offset WHERE item_type = ? AND item_id = ? AND sub_key = ?", (kind, item_id, key))
            return jsonify(ok=True, offset=0, rate=1.0)
        conn.execute("UPDATE sub_offset SET offset = ?, rate = ?, source = ?, prev_offset = NULL, prev_rate = NULL, prev_source = NULL "
                     "WHERE item_type = ? AND item_id = ? AND sub_key = ?", (r["prev_offset"], r["prev_rate"], r["prev_source"], kind, item_id, key))
    return jsonify(ok=True, offset=r["prev_offset"], rate=r["prev_rate"])


# ---- 64.23: fila noturna ---------------------------------------------------------------------------------------------------------
import time  # noqa: E402

_BG = {"thread": None}
BG_RETRY = 24 * 3600          # item sem legenda baixada é conferido de novo depois de 1 dia
BG_SCAN = 500                 # itens olhados por chamada (a conferência de pastas é limitada)
PLAY_IDLE = 120               # s sem salvar progresso para dar a reprodução como parada


def bg_enabled(conn):
    """Interruptor global (Configurações → Reprodução, `settings.subsync_bg`; padrão ligado)."""
    r = conn.execute("SELECT value FROM settings WHERE key = 'subsync_bg'").fetchone()
    return not (r and str(r["value"]) == "0")


def bg_running():
    t = _BG["thread"]
    return bool(t and t.is_alive())


def _playing(conn):
    """Alguém assistiu agora há pouco (o player salva o progresso a cada poucos segundos, inclusive em direct play)."""
    return conn.execute("SELECT 1 FROM progress WHERE updated_at >= datetime('now', ?) LIMIT 1", (f"-{PLAY_IDLE} seconds",)).fetchone() is not None


def _busy(conn, now=None):
    """True se a fila noturna não deve rodar agora: desligada, fora da janela da otimização, otimização/trailers em curso, transcode ou reprodução."""
    from server import optimize, trailers
    window, _ = optimize._settings(conn)
    return (not bg_enabled(conn) or not optimize.in_window(window, now) or optimize.running() or optimize.STATE.get("paused")
            or optimize._transcoding() or trailers.running() or _playing(conn))


def _mark(conn, kind, item_id, key, mtime, status):
    conn.execute("INSERT INTO subsync_bg (item_type, item_id, sub_key, mtime, status, at) VALUES (?, ?, ?, ?, ?, ?) "
                 "ON CONFLICT(item_type, item_id, sub_key) DO UPDATE SET mtime = excluded.mtime, status = excluded.status, at = excluded.at",
                 (kind, item_id, key, mtime, status, int(time.time())))


def next_job(conn):
    """(kind, id, path, info, sub) da próxima legenda **baixada** (SubDL) sem atraso nem razão salvos e ainda não tentada; None se não há.
    Itens sem legenda baixada ganham uma marca de 1 dia para a pasta não ser lida a cada minuto."""
    import json
    from server import subdl
    from server import subtitles as st
    now = int(time.time())
    seen = {(r["item_type"], r["item_id"], r["sub_key"]): r for r in conn.execute("SELECT * FROM subsync_bg")}
    done_items = {(k[0], k[1]) for k, r in seen.items() if k[2] == "" and now - r["at"] < BG_RETRY}
    have = {(r["item_type"], r["item_id"], r["sub_key"]) for r in conn.execute("SELECT item_type, item_id, sub_key FROM sub_offset")}
    looked = 0
    for kind, sql in (("movie", "SELECT id, path, info FROM media WHERE path IS NOT NULL ORDER BY id"),
                      ("episode", "SELECT id, path, info FROM episodes ORDER BY id")):
        for r in conn.execute(sql):
            if (kind, r["id"]) in done_items or not r["path"] or not os.path.isfile(r["path"]):
                continue
            looked += 1
            if looked > BG_SCAN:
                return None
            try:
                subs = [x for x in st.external_subs(r["path"]) if subdl.removable(r["path"], os.path.basename(x["file"]))]
            except OSError:
                continue
            todo = None
            for x in subs:
                key = st.ext_key(x)
                try:
                    mt = os.path.getmtime(x["file"])
                except OSError:
                    continue
                prev = seen.get((kind, r["id"], key))
                if (kind, r["id"], key) in have or (prev and abs(prev["mtime"] - mt) < 1):
                    continue
                todo = todo or (x, mt)
            if todo:
                return kind, r["id"], r["path"], (json.loads(r["info"]) if r["info"] else None), todo[0], todo[1]
            _mark(conn, kind, r["id"], "", 0, "none")
            conn.commit()
    return None


def _work(job):
    from server import subtitles as st
    kind, item_id, path, info, sub, mt = job
    key = st.ext_key(sub)
    if not _LOCK.acquire(blocking=False):
        return
    try:
        _ABORT.clear()
        status = "ok"
        smap = subtitle_map(st._read(sub["file"]))
        if not smap or float((info or {}).get("duration") or 0) > MAX_DURATION:
            status = "skip"
        else:
            vmap = reference_map(path, info, sub.get("lang"), None) or video_map(kind, item_id, path, 0)
            if _ABORT.is_set():
                return  # interrompida: nada é gravado nem marcado, volta à fila
            if not vmap:
                status = "skip"
            else:
                res = correlate(vmap, smap)
                if _ABORT.is_set():
                    return
                with get_db() as conn:
                    if _row(conn, kind, item_id, key):  # o usuário mexeu enquanto calculava: não sobrescreve
                        return
                    if res["confidence"] >= CONF_AUTO and (res["offset"] != 0 or res["rate"] != 1.0):
                        _save(conn, kind, item_id, key, res["offset"], res["rate"])
                    else:
                        status = "low"
        with get_db() as conn:
            _mark(conn, kind, item_id, key, mt, status)
    except Exception:  # noqa: BLE001
        log.exception("AutoSync noturno falhou em %s %s", kind, item_id)
        with get_db() as conn:
            _mark(conn, kind, item_id, key, mt, "skip")
    finally:
        _LOCK.release()


def tick(now=None):
    """Chamado 1×/min por `stream.start_cleanup`: uma legenda por vez, na janela da otimização; para se houver transcode, reprodução,
    fim da janela ou o interruptor for desligado. Devolve o item iniciado (kind, id) ou None."""
    with get_db() as conn:
        busy = _busy(conn, now)
    if bg_running():
        if busy:
            _ABORT.set()
        return None
    if busy or _LOCK.locked():
        return None
    with get_db() as conn:
        job = next_job(conn)
    if not job:
        return None
    _ABORT.clear()
    _BG["thread"] = threading.Thread(target=_work, args=(job,), daemon=True)
    _BG["thread"].start()
    return job[0], job[1]
