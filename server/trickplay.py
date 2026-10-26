"""Miniaturas na barra de progresso (49.1): sprites JPEG + manifest.json em data/trickplay/<tipo>/<id>/."""
import json
import os
import shutil
import subprocess
import time

from flask import Blueprint, abort, send_from_directory

import config
from server.auth import login_required
from server.db import get_db

bp = Blueprint("trickplay", __name__)

ROOT = os.path.join(config.DATA_DIR, "trickplay")
INTERVAL = 10   # s entre quadros
WIDTH = 320     # px
COLS = ROWS = 10
KINDS = ("movie", "episode")


def item_dir(kind, item_id):
    return os.path.join(ROOT, kind, str(int(item_id)))


def has(kind, item_id):
    return os.path.isfile(os.path.join(item_dir(kind, item_id), "manifest.json"))


def generate(kind, item_id, path, info=None, timeout=3600):
    """Gera os sprites do item (só keyframes). Devolve True se o manifest ficou pronto; nunca levanta exceção."""
    if kind not in KINDS or not os.path.isfile(path):
        return False
    dur = float((info or {}).get("duration") or 0)
    if dur and dur < INTERVAL * 2:
        return False
    final = item_dir(kind, item_id)
    tmp = final + ".part"
    try:
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        cmd = ["nice", "-n", "19", "ffmpeg", "-v", "error", "-y", "-skip_frame", "nokey", "-i", path,
               "-an", "-sn", "-dn", "-vf", f"fps=1/{INTERVAL},scale={WIDTH}:-2,tile={COLS}x{ROWS}",
               "-fps_mode", "vfr", "-q:v", "6", os.path.join(tmp, "%d.jpg")]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout, check=True)
        files = sorted((f for f in os.listdir(tmp) if f.endswith(".jpg")), key=lambda f: int(f[:-4]))
        if not files:
            raise RuntimeError("sem sprites")
        vw, vh = _size(info)
        h = int(round(WIDTH * vh / vw / 2.0)) * 2 if vw and vh else int(round(WIDTH * 9 / 16 / 2.0)) * 2
        count = int(dur // INTERVAL) + 1 if dur else len(files) * COLS * ROWS
        manifest = {"interval": INTERVAL, "width": WIDTH, "height": h, "cols": COLS, "rows": ROWS,
                    "count": min(count, len(files) * COLS * ROWS), "sprites": len(files)}
        with open(os.path.join(tmp, "manifest.json"), "w") as f:
            json.dump(manifest, f)
        shutil.rmtree(final, ignore_errors=True)
        os.replace(tmp, final)
        return True
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        return False


def _size(info):
    v = (info or {}).get("video")
    try:
        return int(v.get("width") or 0), int(v.get("height") or 0)
    except (TypeError, ValueError, AttributeError):
        return 0, 0


def remove(kind, item_id):
    shutil.rmtree(item_dir(kind, item_id), ignore_errors=True)


def prune():
    """Apaga as miniaturas de itens que saíram do banco (chamado por prune_missing)."""
    if not os.path.isdir(ROOT):
        return 0
    n = 0
    with get_db() as conn:
        for kind, table in (("movie", "media"), ("episode", "episodes")):
            base = os.path.join(ROOT, kind)
            if not os.path.isdir(base):
                continue
            for d in os.listdir(base):
                ok = d.isdigit() and conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (int(d),)).fetchone()
                if not ok:
                    shutil.rmtree(os.path.join(base, d), ignore_errors=True)
                    n += 1
    return n


@bp.route("/trickplay/<kind>/<int:item_id>/manifest.json")
@login_required
def manifest(kind, item_id):
    from server.stream import get_item  # import tardio (evita ciclo com scanner)
    get_item(kind, item_id)  # acesso e 404
    d = item_dir(kind, item_id)
    if not has(kind, item_id):
        abort(404)
    r = send_from_directory(d, "manifest.json", mimetype="application/json")
    r.headers["Cache-Control"] = "private, max-age=3600"
    return r


@bp.route("/trickplay/<kind>/<int:item_id>/<int:n>.jpg")
@login_required
def sprite(kind, item_id, n):
    from server.stream import get_item  # import tardio (evita ciclo com scanner)
    get_item(kind, item_id)
    d = item_dir(kind, item_id)
    if not os.path.isfile(os.path.join(d, f"{n}.jpg")):
        abort(404)
    r = send_from_directory(d, f"{n}.jpg", mimetype="image/jpeg")
    r.headers["Cache-Control"] = "private, max-age=86400"
    return r


def _pending(conn, library_id, media_id, force):
    """(tipo, id, caminho, info) dos arquivos da biblioteca (ou de um filme/série) que ainda não têm miniaturas."""
    out = []
    q = "SELECT id, path, info FROM media WHERE library_id = ? AND path IS NOT NULL" + (" AND id = ?" if media_id else "")
    for r in conn.execute(q, (library_id, media_id) if media_id else (library_id,)):
        out.append(("movie", r["id"], r["path"], r["info"]))
    q = ("SELECT e.id, e.path, e.info FROM episodes e JOIN media m ON m.id = e.media_id WHERE m.library_id = ? AND e.path IS NOT NULL"
         + (" AND m.id = ?" if media_id else ""))
    for r in conn.execute(q, (library_id, media_id) if media_id else (library_id,)):
        out.append(("episode", r["id"], r["path"], r["info"]))
    return [(k, i, p, inf) for k, i, p, inf in out if not has(k, i)]


def generate_library(library_id, media_id=None, force=False, budget=1800):
    """49.2: etapa \"Gerando miniaturas\" — um item por vez, baixa prioridade (nice), retoma de onde parou (quem já tem manifest é
    pulado) e para ao passar de `budget` s (o próximo exame continua). Sem `force`, só roda se a opção da biblioteca estiver ligada.
    Devolve quantos itens gerou."""
    from server import scanstate
    from server.db import lib_prefs
    with get_db() as conn:
        lib = conn.execute("SELECT type, prefs FROM libraries WHERE id = ?", (library_id,)).fetchone()
        if not lib or (not force and not lib_prefs(lib)["trickplay"]):
            return 0
        todo = _pending(conn, library_id, media_id, force)
    end, n = time.time() + budget, 0
    for kind, iid, path, info in todo:
        if scanstate.cancelled(library_id):
            raise scanstate.ScanCancelled()
        if time.time() > end:
            break
        try:
            info = json.loads(info) if info else None
        except ValueError:
            info = None
        n += bool(generate(kind, iid, path, info))
    return n
