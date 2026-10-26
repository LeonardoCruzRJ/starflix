import config
from flask import Blueprint, render_template

from server.auth import admin_required
from server.db import get_db
from server import markers, stream
from server.scanner import is_scanning

bp = Blueprint("admin_panel", __name__)


@bp.route("/admin")
@admin_required
def panel():
    """Painel admin: totais, bibliotecas com botão de escanear e atalhos para usuários/acessos."""
    with get_db() as conn:
        one = lambda sql: conn.execute(sql).fetchone()[0]
        stats = {
            "users": one("SELECT COUNT(*) FROM users"),
            "libraries": one("SELECT COUNT(*) FROM libraries"),
            "movies": one("SELECT COUNT(*) FROM media m JOIN libraries l ON l.id = m.library_id WHERE l.type = 'movie'"),
            "shows": one("SELECT COUNT(*) FROM media m JOIN libraries l ON l.id = m.library_id WHERE l.type = 'show'"),
            "episodes": one("SELECT COUNT(*) FROM episodes"),
        }
        dv5 = one("SELECT (SELECT COUNT(*) FROM media WHERE info LIKE '%\"hdr\": \"dv5\"%') + (SELECT COUNT(*) FROM episodes WHERE info LIKE '%\"hdr\": \"dv5\"%')")
        libs = conn.execute(
            "SELECT l.id, l.name, l.type, l.path, (SELECT COUNT(*) FROM media m WHERE m.library_id = l.id) AS items "
            "FROM libraries l ORDER BY fold(l.name), l.id"
        ).fetchall()
    return render_template("admin_panel.html", stats=stats, libs=libs, scanning=is_scanning(), no_fp=markers.tools() is None,
                           no_tonemap=stream.has_tonemap() is None, dv5=dv5, base_dir=config.BASE_DIR)  # 48.5: sem impressão de áudio só há capítulos e marcação manual
