"""52.7: gerador da versão otimizada (H.264 High 8 bits 4:2:0, até 1080p, 1ª faixa de áudio em AAC estéreo, `data/optimized/<tipo>/<id>.mp4`).
Fila, janela de horário e uso na reprodução ficam nas etapas 52.8 a 52.10. O arquivo original nunca é alterado."""
import datetime
import json
import os
import shutil
import subprocess
import threading
import time

from flask import Blueprint, jsonify, request

import config
from server.auth import admin_required
from server.db import get_db
from server.caps import parse_caps
from server.stream import SESSIONS, decide_why, hdr_convert, is_bad_pix, tonemap_chain, _hdr_max_height
from server.i18n import E, jerr

MAX_TRIES = 3
MAX_HEIGHT = 1080
DURATION_TOL = 1.0  # s


def out_path(item_type, item_id):
    return os.path.join(config.OPTIMIZED_DIR, item_type, f"{int(item_id)}.mp4")


def _can_copy(info):
    """Vídeo já é H.264 8 bits 4:2:0 SDR e cabe em 1080p: só copia o vídeo (segundos, não horas)."""
    v = (info or {}).get("video") or {}
    return v.get("codec") == "h264" and not is_bad_pix(v) and v.get("hdr", "none") == "none" and (v.get("height") or 0) <= MAX_HEIGHT


def build_cmd(src, part, info):
    """(comando ffmpeg, motivo de recusa). Recusa só fonte HDR sem filtro de tone-map no ffmpeg (as cores sairiam erradas)."""
    v = (info or {}).get("video") or {}
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", src, "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn"]
    if _can_copy(info):
        cmd += ["-c:v", "copy"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p"]
        if v.get("hdr", "none") != "none":
            tm = tonemap_chain(info, None, min(_hdr_max_height(), MAX_HEIGHT))  # 50.2: escala antes do tone-map, teto 1080p
            if not tm:
                return None, "HDR sem filtro de tone-map no ffmpeg"
            cmd += ["-vf", tm, "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
        elif (v.get("height") or 0) > MAX_HEIGHT:
            cmd += ["-vf", f"scale=-2:{MAX_HEIGHT}"]
    cmd += ["-c:a", "aac", "-ac", "2", "-b:a", "160k", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", "-f", "mp4", part]
    low = [b for b in (["nice", "-n", "19"] if shutil.which("nice") else []) + (["ionice", "-c3"] if shutil.which("ionice") else [])]
    return low + cmd, ""


def verify(path, info):
    """(ok, motivo): ffprobe do `.part` — duração ±1 s da original, vídeo H.264 e pix_fmt yuv420p."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
                             capture_output=True, text=True, timeout=60)
        data = json.loads(out.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return False, "ffprobe falhou na saída"
    vs = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not vs:
        return False, "saída sem vídeo"
    if vs.get("codec_name") != "h264" or vs.get("pix_fmt") != "yuv420p":
        return False, f"saída {vs.get('codec_name')}/{vs.get('pix_fmt')}"
    want = float((info or {}).get("duration") or 0)
    got = float((data.get("format") or {}).get("duration") or 0)
    if want and abs(got - want) > DURATION_TOL:
        return False, f"duração {got:.1f}s ≠ {want:.1f}s"
    return True, ""


def _save(item_type, item_id, src, status, reason, tries, out="", size=0):
    try:
        st = os.stat(src)
        s_size, s_mtime = st.st_size, st.st_mtime
    except OSError:
        s_size, s_mtime = 0, 0
    with get_db() as conn:
        conn.execute(
            "INSERT INTO optimized (item_type, item_id, path, src_size, src_mtime, out_path, out_size, status, reason, tries, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(item_type, item_id) DO UPDATE SET path = excluded.path, src_size = excluded.src_size, src_mtime = excluded.src_mtime, out_path = excluded.out_path, "
            "out_size = excluded.out_size, status = excluded.status, reason = excluded.reason, tries = excluded.tries, created_at = excluded.created_at",
            (item_type, item_id, src, s_size, s_mtime, out, size, status, reason, tries, int(time.time())))
        conn.commit()


def _tries(item_type, item_id):
    with get_db() as conn:
        r = conn.execute("SELECT tries FROM optimized WHERE item_type = ? AND item_id = ?", (item_type, item_id)).fetchone()
    return (r["tries"] if r else 0) or 0


def convert(item_type, item_id, src, info, on_progress=None, cancel=None):
    """Converte um item. `on_progress(fração 0–1)` a cada atualização do ffmpeg; `cancel` (threading.Event) interrompe.
    Devolve (status, motivo) e grava a linha em `optimized`: ok; fail (soma `tries`); skip (HDR sem filtro, ou 3 falhas); paused (interrompido: nada é gravado)."""
    final = out_path(item_type, item_id)
    part = final + ".part"
    os.makedirs(os.path.dirname(final), exist_ok=True)
    tries = _tries(item_type, item_id)
    cmd, why = build_cmd(src, part, info)
    if cmd is None:
        _save(item_type, item_id, src, "skip", why, tries)
        return "skip", why
    dur = float((info or {}).get("duration") or 0)
    reason = ""
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except OSError as e:
        proc, reason = None, f"ffmpeg não iniciou: {e}"
    if proc:
        err = []
        t = threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)
        t.start()
        for line in proc.stdout:
            if cancel is not None and cancel.is_set():
                proc.kill()
                reason = "interrompido"
                break
            if on_progress and dur and line.startswith("out_time_us="):
                try:
                    on_progress(min(1.0, max(0.0, int(line.split("=", 1)[1]) / 1e6 / dur)))
                except ValueError:
                    pass
        proc.wait()
        t.join(timeout=5)
        if not reason and proc.returncode != 0:
            reason = ((err[0] if err else "") or f"ffmpeg saiu com {proc.returncode}").strip()[-300:]
        if not reason:
            ok, reason = verify(part, info)
            reason = "" if ok else reason
    if reason:
        try:
            os.remove(part)
        except OSError:
            pass
        if reason == "interrompido":  # 52.8: pausa (reprodução com transcode, fim da janela, botão): o item volta à fila sem gastar tentativa
            return "paused", reason
        tries += 1
        status = "skip" if tries >= MAX_TRIES else "fail"
        _save(item_type, item_id, src, status, reason, tries)
        return status, reason
    os.replace(part, final)
    _save(item_type, item_id, src, "ok", "", tries, final, os.path.getsize(final))
    return "ok", ""


# ---- 52.8: fila, janela de horário e pausa ----
DEFAULT_WINDOW = "02:00-07:00"
STATE = {"thread": None, "cancel": None, "item": None, "progress": 0.0, "started": 0.0, "paused": False}
_LOCK = threading.Lock()
_MANUAL = []  # 52.10: itens pedidos pelo admin (ignoram a janela e os aparelhos marcados), na ordem do pedido
bp = Blueprint("optimize", __name__)


def parse_window(spec):
    """«HH:MM-HH:MM» → (início, fim) em minutos do dia; inválido volta ao padrão."""
    try:
        a, b = (spec or "").split("-")
        f = lambda x: int(x[:2]) * 60 + int(x[3:5]) if len(x) == 5 and x[2] == ":" and 0 <= int(x[:2]) < 24 and 0 <= int(x[3:5]) < 60 else None
        if f(a) is not None and f(b) is not None:
            return f(a), f(b)
    except (ValueError, TypeError):
        pass
    return parse_window(DEFAULT_WINDOW)


def in_window(spec, now=None):
    """True se `now` (datetime local) está na janela; ela pode atravessar a meia-noite; início = fim = sempre."""
    a, b = parse_window(spec)
    now = now or datetime.datetime.now()
    m = now.hour * 60 + now.minute
    if a == b:
        return True
    return a <= m < b if a < b else (m >= a or m < b)


def _settings(conn):
    g = lambda k, d: (conn.execute("SELECT value FROM settings WHERE key = ?", (k,)).fetchone() or [None])[0] or d
    try:
        gb = float(g("optimize_max_gb", 0))
    except ValueError:
        gb = 0.0
    return g("optimize_window", DEFAULT_WINDOW), max(0.0, gb)


def used_bytes(conn):
    return conn.execute("SELECT COALESCE(SUM(out_size), 0) FROM optimized WHERE status = 'ok'").fetchone()[0]


def _valid(row, path):
    """Linha `ok` ainda vale: arquivo da saída existe e a origem não mudou."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    return row["out_path"] and os.path.isfile(row["out_path"]) and row["src_size"] == st.st_size and abs(row["src_mtime"] - st.st_mtime) < 1


def candidates(conn):
    """Itens a otimizar, na ordem: 1) Continue assistindo e Minha Lista, 2) próximos episódios de séries em andamento, 3) o resto por data.
    Candidato = `decide()` mandaria a remux/transcode em ALGUM aparelho marcado em `client_caps`; sem aparelho marcado, lista vazia."""
    caps = [c for c in (parse_caps({"caps": r[0]}) for r in conn.execute("SELECT caps FROM client_caps WHERE required = 1")) if c]
    if not caps:
        return []
    rows = {(r["item_type"], r["item_id"]): r for r in conn.execute("SELECT * FROM optimized")}
    ok_paths = {r["path"] for r in rows.values() if r["status"] == "ok"}
    cont = {(r[0], r[1]) for r in conn.execute("SELECT item_type, item_id FROM progress WHERE watched = 0 AND position > 0")}
    listed = {r[0] for r in conn.execute("SELECT media_id FROM my_list")}
    nxt = set()
    from server.progress import next_episode
    for r in conn.execute("SELECT item_id FROM progress WHERE item_type = 'episode' AND (watched = 1 OR position > 0) ORDER BY updated_at DESC LIMIT 200"):
        n = next_episode(r[0])
        if n:
            nxt.add(("episode", n["id"]))
    items = []
    for r in conn.execute("SELECT id, path, info, added_at FROM media WHERE path IS NOT NULL ORDER BY added_at DESC, id DESC"):
        pr = 1 if ("movie", r["id"]) in cont or r["id"] in listed else 3
        items.append((pr, "movie", r["id"], r["path"], r["info"]))
    for r in conn.execute("SELECT id, media_id, path, info, added_at FROM episodes ORDER BY added_at DESC, id DESC"):
        k = ("episode", r["id"])
        pr = 1 if k in cont else 2 if k in nxt or r["media_id"] in listed else 3
        items.append((pr, "episode", r["id"], r["path"], r["info"]))
    items.sort(key=lambda x: x[0])  # estável: dentro de cada grupo segue a data (mais novo primeiro)
    out, seen = [], set()
    for pr, typ, iid, path, raw in items:
        if not path or path in seen or not raw:
            continue
        row = rows.get((typ, iid))
        if row and (row["status"] == "skip" or (row["status"] == "fail" and row["tries"] >= MAX_TRIES) or (row["status"] == "ok" and _valid(row, path))):
            continue
        if path in ok_paths and not row:  # arquivo repetido (outro item) já otimizado
            continue
        try:
            info = json.loads(raw)
        except ValueError:
            continue
        if not info.get("video") or info.get("error"):
            continue
        if any(decide_why(path, info, hdr_conv=hdr_convert(info, "1" if c.hdr else "0"), caps=c)[0] != "direct" for c in caps):
            seen.add(path)
            out.append((typ, iid, path, info))
    return out


def running():
    t = STATE["thread"]
    return bool(t and t.is_alive())


def pause_for_play():
    """Alguém começou uma reprodução com transcode: mata o ffmpeg da otimização (o item volta à fila)."""
    if running() and STATE["cancel"] is not None:
        STATE["cancel"].set()


def pause():
    STATE["paused"] = True
    pause_for_play()


def resume():
    STATE["paused"] = False


def _transcoding():
    return any(s["key"][2] == "transcode" and s["proc"].poll() is None for s in list(SESSIONS.values()))


def _work(item, cancel, manual=False):
    typ, iid, path, info = item
    try:
        res = convert(typ, iid, path, info, on_progress=lambda f: STATE.update(progress=f), cancel=cancel)
        if manual and res[0] == "paused":  # pausa (reprodução, limite, botão): o pedido do admin volta ao começo da fila
            _MANUAL.insert(0, (typ, iid))
    except Exception as e:  # noqa: BLE001
        print(f"[optimize] {typ} {iid}: {e}", flush=True)
    finally:
        STATE.update(item=None, progress=0.0, manual=False)


def _next_manual(conn):
    """52.10: próximo item pedido pelo admin que ainda precisa de conversão, ou None."""
    while _MANUAL:
        typ, iid = _MANUAL.pop(0)
        r = conn.execute("SELECT path, info FROM media WHERE id = ?" if typ == "movie" else "SELECT path, info FROM episodes WHERE id = ?", (iid,)).fetchone()
        if not r or not r["path"] or not r["info"]:
            continue
        try:
            info = json.loads(r["info"])
        except ValueError:
            continue
        if not info.get("video") or info.get("error"):
            continue
        row = conn.execute("SELECT * FROM optimized WHERE item_type = ? AND item_id = ?", (typ, iid)).fetchone()
        if row and row["status"] == "ok" and _valid(row, r["path"]):
            continue
        return (typ, iid, r["path"], info)
    return None


def tick(now=None):
    """Chamado no laço de `stream.start_cleanup` (1×/min): uma conversão por vez, só na janela (pedido manual do admin ignora a janela), sem transcode de alguém, respeitando disco."""
    with _LOCK:
        with get_db() as conn:
            window, max_gb = _settings(conn)
            over = max_gb > 0 and used_bytes(conn) >= max_gb * 1024 ** 3
        if running():
            if STATE["paused"] or (not STATE.get("manual") and not in_window(window, now)) or _transcoding() or over:
                pause_for_play()
            return None
        if STATE["paused"] or over or _transcoding():
            return None
        if config.MIN_FREE_GB > 0:
            os.makedirs(config.OPTIMIZED_DIR, exist_ok=True)
            if shutil.disk_usage(config.OPTIMIZED_DIR).free < config.MIN_FREE_GB * 1024 ** 3:
                return None
        with get_db() as conn:
            item = _next_manual(conn)
            manual = item is not None
            if not manual:
                if not in_window(window, now):
                    return None
                cand = candidates(conn)
                item = cand[0] if cand else None
        if not item:
            return None
        cancel = threading.Event()
        STATE.update(cancel=cancel, item=item[:2], progress=0.0, started=time.time(), manual=manual)
        STATE["thread"] = threading.Thread(target=_work, args=(item, cancel, manual), daemon=True)
        STATE["thread"].start()
        return item[:2]


# ---- 52.9: uso na reprodução e invalidação ----
def _unlink(path):
    try:
        if path:
            os.remove(path)
    except OSError:
        pass


def drop(item_type, item_id):
    """Apaga a versão otimizada (arquivo e linha) do item."""
    with get_db() as conn:
        r = conn.execute("SELECT out_path FROM optimized WHERE item_type = ? AND item_id = ?", (item_type, item_id)).fetchone()
        conn.execute("DELETE FROM optimized WHERE item_type = ? AND item_id = ?", (item_type, item_id))
        conn.commit()
    if r:
        _unlink(r["out_path"])


def find(item_type, item_id, path):
    """Caminho da versão otimizada válida do item, ou None. Origem mudou (`src_size`/`src_mtime`) ou saída sumiu: apaga arquivo e linha.
    Arquivo repetido (outro item com o mesmo `path` já otimizado) reaproveita a do outro, sem gerar duas."""
    try:
        with get_db() as conn:
            r = conn.execute("SELECT * FROM optimized WHERE item_type = ? AND item_id = ?", (item_type, item_id)).fetchone()
            other = None if r else conn.execute("SELECT * FROM optimized WHERE path = ? AND status = 'ok' LIMIT 1", (path,)).fetchone()
        if r is None:
            return other["out_path"] if other and _valid(other, path) else None
        if r["status"] != "ok":
            return None
        if r["path"] == path and _valid(r, path):
            return r["out_path"]
        drop(item_type, item_id)
    except Exception:
        pass
    return None


def prune():
    """Chamado em `prune_missing`: apaga as versões otimizadas (arquivo e linha) de filmes/episódios que saíram do banco."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT item_type, item_id, out_path FROM optimized WHERE (item_type = 'movie' AND item_id NOT IN (SELECT id FROM media)) "
            "OR (item_type = 'episode' AND item_id NOT IN (SELECT id FROM episodes))").fetchall()
        for r in rows:
            conn.execute("DELETE FROM optimized WHERE item_type = ? AND item_id = ?", (r["item_type"], r["item_id"]))
        conn.commit()
    for r in rows:
        _unlink(r["out_path"])


# ---- 52.10: painel e menus ----
def _title(conn, typ, iid):
    if typ == "movie":
        r = conn.execute("SELECT title FROM media WHERE id = ?", (iid,)).fetchone()
        return (r["title"] if r else None) or E("op.item_movie", n=iid)
    r = conn.execute("SELECT e.season, e.episode, e.title, m.title AS show FROM episodes e JOIN media m ON m.id = e.media_id WHERE e.id = ?", (iid,)).fetchone()
    if not r:
        return E("op.item_episode", n=iid)
    return f"{r['show'] or E('common.show')} · S{r['season'] or 0:02d}E{r['episode'] or 0:02d}"


def refs_from_files(files):
    """[(tabela, id, caminho)] de `admin_edit._scope` → [(tipo, id)]."""
    return [("movie" if t == "media" else "episode", i) for t, i, p in files if p]


def refs_for_library(lid):
    with get_db() as conn:
        refs = [("movie", r[0]) for r in conn.execute("SELECT id FROM media WHERE library_id = ? AND path IS NOT NULL", (lid,))]
        refs += [("episode", r[0]) for r in conn.execute("SELECT e.id FROM episodes e JOIN media m ON m.id = e.media_id WHERE m.library_id = ?", (lid,))]
    return refs


def enqueue(refs):
    """Pedido do admin ("Otimizar este item/biblioteca"): entra na frente da fila automática, fora da janela de horário; `skip`/`fail` anteriores são zerados.
    Devolve quantos entraram (os que já têm otimizada válida não contam)."""
    n = 0
    with get_db() as conn:
        for typ, iid in refs:
            if (typ, iid) in _MANUAL or STATE.get("item") == (typ, iid):
                continue
            r = conn.execute("SELECT path, info FROM media WHERE id = ?" if typ == "movie" else "SELECT path, info FROM episodes WHERE id = ?", (iid,)).fetchone()
            if not r or not r["path"] or not r["info"]:
                continue
            row = conn.execute("SELECT * FROM optimized WHERE item_type = ? AND item_id = ?", (typ, iid)).fetchone()
            if row and row["status"] == "ok" and _valid(row, r["path"]):
                continue
            if row and row["status"] != "ok":
                conn.execute("DELETE FROM optimized WHERE item_type = ? AND item_id = ?", (typ, iid))
            _MANUAL.append((typ, iid))
            n += 1
        conn.commit()
    if n:
        threading.Thread(target=tick, daemon=True).start()
    return n


def remove_refs(refs):
    """"Remover versão otimizada": apaga arquivo e linha (qualquer status) dos itens; devolve quantos tinham linha."""
    n = 0
    for typ, iid in refs:
        if (typ, iid) in _MANUAL:
            _MANUAL.remove((typ, iid))
        if STATE.get("item") == (typ, iid):
            pause_for_play()
        with get_db() as conn:
            had = conn.execute("SELECT 1 FROM optimized WHERE item_type = ? AND item_id = ?", (typ, iid)).fetchone()
        if had:
            drop(typ, iid)
            n += 1
    return n


def clear_all():
    """"Apagar todas": apaga as versões prontas (arquivo e linha); `skip`/`fail` ficam (guardam o motivo). Esvazia os pedidos manuais."""
    _MANUAL.clear()
    pause_for_play()
    with get_db() as conn:
        rows = conn.execute("SELECT item_type, item_id, out_path FROM optimized WHERE status = 'ok'").fetchall()
        conn.execute("DELETE FROM optimized WHERE status = 'ok'")
        conn.commit()
    for r in rows:
        _unlink(r["out_path"])
    return len(rows)


def status():
    with get_db() as conn:
        window, max_gb = _settings(conn)
        used = used_bytes(conn)
        n_ok = conn.execute("SELECT COUNT(*) FROM optimized WHERE status = 'ok'").fetchone()[0]
        queue = [(t, i) for t, i in _MANUAL]
        try:
            queue += [(t, i) for t, i, _p, _n in candidates(conn) if (t, i) not in queue and (t, i) != STATE.get("item")]
        except Exception:  # noqa: BLE001
            pass
        cur = STATE.get("item")
        running_ = None
        if cur and running():
            f = float(STATE.get("progress") or 0)
            el = time.time() - (STATE.get("started") or time.time())
            running_ = {"type": cur[0], "id": cur[1], "title": _title(conn, *cur), "progress": round(f, 3),
                        "eta": int(el / f * (1 - f)) if f > 0.02 else None, "manual": bool(STATE.get("manual"))}
        skips = [{"type": r["item_type"], "id": r["item_id"], "title": _title(conn, r["item_type"], r["item_id"]), "status": r["status"], "reason": r["reason"] or ""}
                 for r in conn.execute("SELECT item_type, item_id, status, reason FROM optimized WHERE status IN ('skip', 'fail') ORDER BY created_at DESC LIMIT 100")]
        return {"paused": bool(STATE["paused"]), "running": running_, "window": window, "in_window": in_window(window), "max_gb": max_gb,
                "used": used, "ok": n_ok, "queue": {"total": len(queue), "items": [{"title": _title(conn, t, i)} for t, i in queue[:10]]}, "skips": skips}


@bp.route("/admin/optimize/data")
@admin_required
def data():
    return jsonify(status())


@bp.route("/admin/optimize/pause", methods=["POST"])
@admin_required
def pause_route():
    d = request.get_json(silent=True)
    if not isinstance(d, dict) or not isinstance(d.get("paused"), bool):
        return jerr("err.dados_invalidos", 400)
    pause() if d["paused"] else resume()
    return jsonify(status())


@bp.route("/admin/optimize/clear", methods=["POST"])
@admin_required
def clear_route():
    clear_all()
    return jsonify(status())
