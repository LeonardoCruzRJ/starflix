"""39.2: aba Destaques das configurações do administrador (/admin/home): ordem (arrastar e soltar), quais seções aparecem,
quantas fileiras vêm do TMDB (TMDB1, TMDB2…) e o máximo de fileiras do Início. O layout vale para todos os perfis."""
from flask import Blueprint, jsonify, render_template, request

from server.auth import admin_required
from server.db import get_db
from server.home_rows import (LABELS, SLOT, TMDB_KEYS, clean_layout, default_layout, load_layout, reset_layout,
                              save_layout, LAYOUT_MAX_ROWS)
from server.i18n import jerr, tr

bp = Blueprint("admin_home", __name__)


def _payload(conn):
    saved = load_layout(conn)
    lay = saved or default_layout()
    items = []
    for k in lay["order"]:
        if k.startswith(SLOT):
            n = int(k[len(SLOT):])
            items.append({"key": k, "label": f"TMDB{n}", "tmdb": True, "on": k not in lay["hidden"]})
        else:
            items.append({"key": k, "label": tr(LABELS.get(k, k)), "tmdb": False, "on": k not in lay["hidden"]})
    return {"items": items, "tmdb": lay["tmdb"], "tmdb_max": len(TMDB_KEYS), "max_rows": lay["max_rows"],
            "max_rows_limit": LAYOUT_MAX_ROWS, "saved": saved is not None}


@bp.route("/admin/home")
@admin_required
def page():
    return render_template("admin_home.html")


@bp.route("/admin/home/data")
@admin_required
def data():
    with get_db() as conn:
        return jsonify(_payload(conn))


@bp.route("/admin/home/save", methods=["POST"])
@admin_required
def save():
    """Corpo: {order: [keys], hidden: [keys], tmdb: n, max_rows: n}."""
    d = request.get_json(silent=True)
    try:
        lay = clean_layout(d)
    except ValueError as e:
        return jerr(e, 400)
    with get_db() as conn:
        save_layout(conn, lay)
        return jsonify(_payload(conn))


@bp.route("/admin/home/reset", methods=["POST"])
@admin_required
def reset():
    with get_db() as conn:
        reset_layout(conn)
        return jsonify(_payload(conn))
