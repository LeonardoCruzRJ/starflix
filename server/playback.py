"""50.3: Configurações → Reprodução (/admin/playback): HDR (automático, sempre converter, nunca converter) e altura máxima
do tone-map; 52.5: Direct play (automático = usa `caps`, conservador = lista de antes). Valores em `settings` (hdr_mode, hdr_max_height, direct_policy)."""
from flask import Blueprint, jsonify, render_template, request

from server.auth import admin_required
from server.db import get_db
from server.libraries import get_setting
from server.i18n import jerr

bp = Blueprint("playback", __name__)

HDR_MODES = ("auto", "always", "never")
HEIGHTS = (720, 1080, 2160)
DIRECT_POLICIES = ("auto", "conservative")


def _win_ok(w):
    """52.8: «HH:MM-HH:MM»."""
    import re
    m = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)", w or "")
    return bool(m)


def _payload(conn):
    try:
        h = int(get_setting(conn, "hdr_max_height", 1080))
    except (TypeError, ValueError):
        h = 1080
    m = get_setting(conn, "hdr_mode", "auto")
    dp = get_setting(conn, "direct_policy", "auto")
    win = get_setting(conn, "optimize_window", "02:00-07:00")
    try:
        gb = max(0, int(float(get_setting(conn, "optimize_max_gb", 0))))
    except (TypeError, ValueError):
        gb = 0
    return {"optimize_window": win if _win_ok(win) else "02:00-07:00", "optimize_max_gb": gb, **{"hdr_mode": m if m in HDR_MODES else "auto", "hdr_max_height": h if h in HEIGHTS else 1080, "heights": list(HEIGHTS),
            "direct_policy": dp if dp in DIRECT_POLICIES else "auto"}}


@bp.route("/admin/playback")
@admin_required
def page():
    return render_template("admin_playback.html")


@bp.route("/admin/playback/data")
@admin_required
def data():
    with get_db() as conn:
        return jsonify(_payload(conn))


@bp.route("/admin/playback/save", methods=["POST"])
@admin_required
def save():
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return jerr("err.dados_invalidos", 400)
    mode, h = d.get("hdr_mode"), d.get("hdr_max_height")
    with get_db() as conn:
        cur = _payload(conn)
    dp = d.get("direct_policy", cur["direct_policy"])  # ausente = mantém o atual
    win, gb = d.get("optimize_window", cur["optimize_window"]), d.get("optimize_max_gb", cur["optimize_max_gb"])
    if mode not in HDR_MODES or h not in HEIGHTS or dp not in DIRECT_POLICIES or not _win_ok(win) or isinstance(gb, bool) or not isinstance(gb, int) or not 0 <= gb <= 100000:
        return jerr("err.opcao_invalida", 400)
    with get_db() as conn:
        for k, v in (("hdr_mode", mode), ("hdr_max_height", str(h)), ("direct_policy", dp), ("optimize_window", win), ("optimize_max_gb", str(gb))):
            conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, v))
        conn.commit()
        return jsonify(_payload(conn))
