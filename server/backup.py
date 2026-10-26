"""Backup do banco (51.1): cópia consistente (VACUUM INTO) + fotos de perfil em data/backups/starflix-AAAAMMDD-HHMMSS.zip."""
import logging
import os
import re
import sqlite3
import threading
import time
import zipfile

from flask import Blueprint, abort, jsonify, request, send_from_directory

import config
from server.auth import admin_required
from server.db import get_db
from server.i18n import jerr

bp = Blueprint("backup", __name__)
log = logging.getLogger("starflix.backup")
_lock = threading.Lock()
NAME = re.compile(r"^starflix-\d{8}-\d{6}\.zip$")
KEEP_DEFAULT = 4


def keep():
    """Quantos backups guardar (`settings.backup_keep`, padrão 4, mínimo 1)."""
    from server.libraries import get_setting
    try:
        with get_db() as conn:
            return max(1, int(get_setting(conn, "backup_keep", KEEP_DEFAULT)))
    except (TypeError, ValueError, sqlite3.Error):
        return KEEP_DEFAULT


def list_backups():
    """[{name, size, mtime}] do mais novo para o mais antigo."""
    if not os.path.isdir(config.BACKUPS_DIR):
        return []
    out = []
    for n in os.listdir(config.BACKUPS_DIR):
        if NAME.match(n):
            st = os.stat(os.path.join(config.BACKUPS_DIR, n))
            out.append({"name": n, "size": st.st_size, "mtime": int(st.st_mtime)})
    return sorted(out, key=lambda b: b["name"], reverse=True)


def _copy_db(dest):
    """Cópia consistente do banco em `dest`, sem parar o servidor: VACUUM INTO (SQLite >= 3.27) ou Connection.backup()."""
    src = sqlite3.connect(config.DB_PATH, timeout=30)
    try:
        if sqlite3.sqlite_version_info >= (3, 27, 0):
            src.execute("VACUUM INTO ?", (dest,))
        else:
            out = sqlite3.connect(dest)
            try:
                src.backup(out)
            finally:
                out.close()
    finally:
        src.close()


def _integrity_ok(path):
    con = sqlite3.connect(path)
    try:
        return con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        con.close()


def _rotate(n):
    for b in list_backups()[n:]:
        try:
            os.remove(os.path.join(config.BACKUPS_DIR, b["name"]))
        except OSError:
            pass


def backup_now():
    """Faz um backup agora. Devolve o nome do arquivo, ou None se já há um em andamento ou se falhou (o motivo vai para o log)."""
    if not _lock.acquire(blocking=False):
        return None
    tmp_db = tmp_zip = None
    try:
        os.makedirs(config.BACKUPS_DIR, exist_ok=True)
        name = time.strftime("starflix-%Y%m%d-%H%M%S.zip")
        final = os.path.join(config.BACKUPS_DIR, name)
        tmp_db = final + ".db.part"
        tmp_zip = final + ".part"
        for t in (tmp_db, tmp_zip):
            if os.path.exists(t):
                os.remove(t)
        _copy_db(tmp_db)
        if not _integrity_ok(tmp_db):
            raise RuntimeError("integrity_check da cópia falhou")
        fd = os.open(tmp_zip, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # contém as chaves de API: só o dono lê
        with os.fdopen(fd, "wb") as f, zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(tmp_db, "starflix.db")
            if os.path.isdir(config.AVATARS_DIR):
                for fn in sorted(os.listdir(config.AVATARS_DIR)):
                    p = os.path.join(config.AVATARS_DIR, fn)
                    if os.path.isfile(p):
                        z.write(p, "avatars/" + fn)
        os.replace(tmp_zip, final)
        tmp_zip = None
        os.chmod(final, 0o600)
        with get_db() as conn:
            conn.execute("INSERT INTO settings (key, value) VALUES ('backup_last', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                         (str(int(time.time())),))
            conn.commit()
        _rotate(keep())
        log.info("backup feito: %s", name)
        return name
    except Exception:
        log.exception("falha ao fazer o backup")
        return None
    finally:
        for t in (tmp_db, tmp_zip):
            if t and os.path.exists(t):
                try:
                    os.remove(t)
                except OSError:
                    pass
        _lock.release()


def days():
    """Intervalo entre backups em dias (`settings.backup_days`, padrão 7; 0 desliga)."""
    from server.libraries import get_setting
    try:
        with get_db() as conn:
            return max(0, int(get_setting(conn, "backup_days", 7)))
    except (TypeError, ValueError, sqlite3.Error):
        return 7


def last_time():
    """Instante do último backup: `settings.backup_last` ou, se faltar, o arquivo mais novo; 0 se nunca houve."""
    from server.libraries import get_setting
    try:
        with get_db() as conn:
            v = get_setting(conn, "backup_last")
        if v:
            return float(v)
    except (TypeError, ValueError, sqlite3.Error):
        pass
    b = list_backups()
    return float(b[0]["mtime"]) if b else 0.0


def next_time():
    """Próximo backup previsto (instante) ou None se desligado."""
    d = days()
    if not d:
        return None
    last = last_time()
    return time.time() if not last else last + d * 86400  # 53.1: nunca houve backup = vence já (a agenda faz na próxima hora)


def maybe_backup(now=None):
    """51.2: chamado de hora em hora (e na subida) por `stream.start_cleanup`. Faz um backup se passaram `backup_days` desde o último
    (também logo após o servidor ter ficado desligado); adia se há exame de biblioteca em andamento. Nunca levanta exceção.
    Devolve o nome do arquivo, ou None."""
    try:
        d = days()
        if not d or (now if now is not None else time.time()) - last_time() < d * 86400:
            return None
        from server.scanner import is_scanning
        if is_scanning():
            log.info("backup adiado: exame de biblioteca em andamento")
            return None
        return backup_now()  # falha: backup_last não muda, então a hora seguinte tenta de novo
    except Exception:
        log.exception("falha na agenda do backup")
        return None


# ---- Painel (51.3): rotas só de admin ----
def _payload():
    nxt = next_time()
    return {"backups": list_backups(), "last": int(last_time()) or None, "next": int(nxt) if nxt else None,
            "running": _lock.locked(), "days": days(), "keep": keep()}


def _safe(name):
    """Nome de arquivo de backup válido (sem caminhos nem `..`) que existe; senão 404."""
    if not NAME.match(name or "") or not os.path.isfile(os.path.join(config.BACKUPS_DIR, name)):
        abort(404)
    return name


@bp.route("/admin/backup/list")
@admin_required
def route_list():
    return jsonify(_payload())


@bp.route("/admin/backup/run", methods=["POST"])
@admin_required
def route_run():
    """Faz um backup agora, em segundo plano (202); 409 se já há um em andamento."""
    if _lock.locked():
        return jerr("err.ja_ha_backup_andamento", 409)
    threading.Thread(target=backup_now, daemon=True).start()
    time.sleep(0.2)  # dá tempo de a thread pegar a trava para o próximo /list já mostrar "fazendo"
    return jsonify(ok=True, pending=True), 202


@bp.route("/admin/backup/settings", methods=["POST"])
@admin_required
def route_settings():
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return jerr("err.dados_invalidos", 400)
    try:
        n_days, n_keep = int(d.get("days")), int(d.get("keep"))
    except (TypeError, ValueError):
        return jerr("err.informe_numeros_inteiros", 400)
    if not 0 <= n_days <= 365 or not 1 <= n_keep <= 30:
        return jerr("err.dias_0_365_0_desliga", 400)
    with get_db() as conn:
        for k, v in (("backup_days", n_days), ("backup_keep", n_keep)):
            conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, str(v)))
        conn.commit()
    _rotate(n_keep)
    return jsonify(_payload())


@bp.route("/admin/backup/<name>")
@admin_required
def route_download(name):
    return send_from_directory(config.BACKUPS_DIR, _safe(name), as_attachment=True)


@bp.route("/admin/backup/<name>/delete", methods=["POST"])
@admin_required
def route_delete(name):
    os.remove(os.path.join(config.BACKUPS_DIR, _safe(name)))
    return jsonify(_payload())
