"""53.3: o que o servidor está fazendo agora (exame, otimização, backup, transcodes), para o tooltip do ícone Painel."""
import time
from server.i18n import E

from flask import Blueprint, jsonify

from server.auth import admin_required
from server.db import get_db

bp = Blueprint("activity", __name__)


def current():
    """Lista de {text, secs?, pct?} só do que está em andamento; vazia se não há nada."""
    out = []
    try:
        from server import scanner
        pr = scanner.progress() if scanner.is_scanning() else {}
        if pr:
            name = ""
            try:
                with get_db() as conn:
                    r = conn.execute("SELECT name FROM libraries WHERE id = ?", (pr.get("lib"),)).fetchone()
                name = r["name"] if r else ""
            except Exception:  # noqa: BLE001
                pass
            out.append({"text": (name + ": " if name else "") + str(pr.get("stage") or "Examinando") + "…",
                        "secs": int(time.time() - pr.get("since", time.time()))})
    except Exception:  # noqa: BLE001
        pass
    try:
        from server import optimize
        if optimize.running() and optimize.STATE.get("item"):
            with get_db() as conn:
                title = optimize._title(conn, *optimize.STATE["item"])
            f = float(optimize.STATE.get("progress") or 0)
            out.append({"text": "Otimizando " + str(title), "pct": int(f * 100)})
    except Exception:  # noqa: BLE001
        pass
    try:
        from server import backup
        if backup._lock.locked():
            out.append({"text": "Fazendo o backup…"})
    except Exception:  # noqa: BLE001
        pass
    try:
        from server import stream
        procs = [s for s in list(stream.SESSIONS.values()) if s["proc"].poll() is None]
        n = len([s for s in procs if not s.get("warm")])
        w = len(procs) - n
        if n:
            out.append({"text": E("act.transcoding", n=n)})
        if w:
            out.append({"text": E("act.warming")})
    except Exception:  # noqa: BLE001
        pass
    return out


@bp.route("/admin/activity")
@admin_required
def route_activity():
    r = jsonify(items=current())
    r.headers["Cache-Control"] = "no-store"
    return r
