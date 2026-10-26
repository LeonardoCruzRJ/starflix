import time
from functools import wraps
from urllib.parse import quote

from flask import Blueprint, abort, jsonify, redirect, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from server.db import get_db
from server.i18n import E, jerr

bp = Blueprint("auth", __name__)


API_PREFIXES = ("/stream/", "/progress/", "/next/", "/continue", "/list/", "/stars/", "/bulk/", "/account/", "/playlists", "/home/", "/api/", "/tv/", "/phone/")


def unauthorized():
    """Sessão ausente/expirada: 401 JSON para chamadas de API (fetch), redirect para páginas HTML."""
    p = request.path
    api = p.startswith(API_PREFIXES) or (p.startswith("/admin/") and "text/html" not in request.headers.get("Accept", "")) \
        or (p.startswith("/library/") and p.endswith(("/pin", "/info", "/smart/preview", "/rows", "/view-prefs"))) \
        or (p.startswith("/playlist/") and (p.endswith("/edit") or "/image/" in p))
    if api:
        return jerr("err.sessao_expirada", 401)
    if p in ("/tv", "/phone") and request.method == "GET":  # 40.3: depois do login volta à página de pareamento (com o código do QR)
        return redirect("/login?next=" + quote(request.full_path.rstrip("?")))
    return redirect("/login")


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return unauthorized()
        return f(*args, **kwargs)

    return wrapper


def admin_required(f):
    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        with get_db() as conn:
            u = conn.execute("SELECT is_admin FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        if not u or not u["is_admin"]:
            abort(403)
        return f(*args, **kwargs)

    return wrapper


def has_users():
    with get_db() as conn:
        return conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


@bp.route("/setup", methods=["GET", "POST"])
def setup():
    if has_users():
        return redirect("/")
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or len(password) < 4:
            error = E("err.informe_usuario_senha_minimo_4")
        else:
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
                    (username, generate_password_hash(password)),
                )
            return redirect("/")
    return render_template("setup.html", error=error)


MAX_FAILS = 5
BLOCK_SECONDS = 300
_FAILS = {}  # ip -> (falhas seguidas, instante da última falha)


def _blocked(ip):
    n, last = _FAILS.get(ip, (0, 0))
    if n >= MAX_FAILS and time.time() - last < BLOCK_SECONDS:
        return True
    if n >= MAX_FAILS:
        _FAILS.pop(ip, None)
    return False


def _fail(ip):
    n, _ = _FAILS.get(ip, (0, 0))
    _FAILS[ip] = (n + 1, time.time())


def _safe_next(v):
    """Destino pós-login aceito: só as páginas de pareamento (/tv, /tv?code=… e /phone), nunca outro endereço."""
    v = v or ""
    return v if v in ("/tv", "/phone") or v.startswith("/tv?") else ""


@bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    nxt = _safe_next(request.values.get("next"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        ip = request.remote_addr
        if _blocked(ip):
            return render_template("login.html", error=E("err.muitas_tentativas_aguarde_alguns_minutos"), next=nxt), 429
        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE casefold(username) = casefold(?) ORDER BY (username = ?) DESC LIMIT 1", (username, username)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            _FAILS.pop(ip, None)
            session.clear()
            session.permanent = True  # clear() zera a flag; sem isso o cookie vira de sessão
            session["user_id"] = user["id"]
            session["sv"] = user["session_ver"] or 0
            return redirect(nxt or "/")
        _fail(ip)
        error = E("err.usuario_ou_senha_invalidos")
    return render_template("login.html", error=error, next=nxt)


@bp.route("/logout")
def logout():
    session.clear()
    return redirect("/login")
