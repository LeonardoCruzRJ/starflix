import os
import re
import secrets
from datetime import timedelta

from werkzeug.exceptions import HTTPException

from flask.sessions import SecureCookieSessionInterface
from flask import Flask, g, jsonify, redirect, render_template, request, session

import config
from server.auth import bp as auth_bp, has_users, login_required, unauthorized
from server.db import display_title, get_db, init_db, lib_prefs
from server import i18n
from server.i18n import jerr
from server.account import avatar_url, bp as account_bp, profile_photo_url, user_prefs
from server.admin_edit import bp as admin_edit_bp
from server.admin_media import bp as admin_media_bp
from server.admin_home import bp as admin_home_bp
from server.admin_panel import bp as admin_panel_bp
from server.admin_server import bp as admin_server_bp, load_port
from server.phone_auth import bp as phone_auth_bp, phone_alive, phone_token_valid
from server.agents import bp as agents_bp, load_keys
from server.browse import bp as browse_bp
from server.bulk import bp as bulk_bp
from server.collections import bp as collections_bp
from server.images import bp as images_bp
from server.mylist import bp as mylist_bp, my_list_items
from server.libraries import bp as libraries_bp, get_setting, pinned_libraries, visible_libraries
from server.library_access import bp as library_access_bp
from server.playlists import bp as playlists_bp
from server.profiles import bp as profiles_bp
from server.progress import bp as progress_bp, continue_watching
from server.discovery import start as start_discovery
from server.scanner import start_periodic
from server.search import bp as search_bp
from server.smart import bp as smart_bp
from server.home_rows import bp as home_rows_bp
from server.tv_api import bp as tv_api_bp
from server.tv_auth import bp as tv_auth_bp, bearer_token, device_for_token, profile_of
from server.markers import bp as markers_bp
from server.trickplay import bp as trickplay_bp
from server.playback import bp as playback_bp
from server.devices import bp as devices_bp
from server.optimize import bp as optimize_bp
from server.backup import bp as backup_bp
from server.activity import bp as activity_bp
from server.people import bp as people_bp
from server.stream import bp as stream_bp, start_cleanup
from server.subtitles import bp as subtitles_bp
from server.users import bp as users_bp

init_db()
load_keys()  # 45.5: chaves de API (TMDB/TVDB/OMDB) do banco para o config
load_port()  # 60.1: porta salva em Configurações → Servidor (padrão 32000)


def load_secret():
    key = os.environ.get("STARFLIX_SECRET")
    if key:
        return key
    path = os.path.join(config.DATA_DIR, "secret.key")
    if not os.path.exists(path):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
    os.chmod(path, 0o600)
    with open(path) as f:
        return f.read().strip()


class _Sessions(SecureCookieSessionInterface):
    """40.4: chamadas da TV (Bearer) usam o token no lugar do cookie e não criam nem alteram o cookie de sessão."""

    def save_session(self, app, session, response):
        if g.get("tv_device"):
            return None
        return super().save_session(app, session, response)


app = Flask(__name__, template_folder="web/templates", static_folder="web/static")
app.session_interface = _Sessions()
app.secret_key = load_secret()
app.config.update(
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_NAME="starflix_session",
)
app.register_blueprint(auth_bp)
app.register_blueprint(users_bp)
app.register_blueprint(profiles_bp)
app.register_blueprint(account_bp)
app.register_blueprint(libraries_bp)
app.register_blueprint(images_bp)
app.register_blueprint(collections_bp)
app.register_blueprint(mylist_bp)
app.register_blueprint(bulk_bp)
app.register_blueprint(admin_media_bp)
app.register_blueprint(admin_edit_bp)
app.register_blueprint(admin_panel_bp)
app.register_blueprint(admin_server_bp)
app.register_blueprint(admin_home_bp)
app.register_blueprint(agents_bp)
app.register_blueprint(library_access_bp)
app.register_blueprint(stream_bp)
app.register_blueprint(progress_bp)
app.register_blueprint(browse_bp)
app.register_blueprint(subtitles_bp)
app.register_blueprint(search_bp)
app.register_blueprint(smart_bp)
app.register_blueprint(playlists_bp)
app.register_blueprint(home_rows_bp)
app.register_blueprint(tv_auth_bp)
app.register_blueprint(phone_auth_bp)
app.register_blueprint(tv_api_bp)
app.register_blueprint(people_bp)
app.register_blueprint(markers_bp)
app.register_blueprint(trickplay_bp)
app.register_blueprint(playback_bp)
app.register_blueprint(devices_bp)
app.register_blueprint(optimize_bp)
app.register_blueprint(backup_bp)
app.register_blueprint(activity_bp)
from server.branding import bp as branding_bp  # 59.1
app.register_blueprint(branding_bp)
from server.i18n_api import bp as i18n_api_bp  # 59.3
app.register_blueprint(i18n_api_bp)

PUBLIC = ("health", "auth.setup", "auth.login", "static", "tv_auth.code_new", "tv_auth.code_poll", "admin_server.info", "branding.serve", "i18n_api.catalog", "i18n_api.set_lang", "phone_auth.connect_page", "phone_auth.claim", "phone_auth.session_from_token", "phone_auth.tv_ticket", "phone_auth.phone_me", "phone_auth.tv_claim")  # 40.2: a TV ainda não tem sessão


@app.before_request
def gate():
    session.permanent = True
    ep = request.endpoint
    if ep in PUBLIC:
        return None
    if not has_users():
        return redirect("/setup")
    token = bearer_token()
    if token is not None:
        with get_db() as conn:
            dev = device_for_token(conn, token)
            # 58.12: o WebView do celular repete o `Authorization` (token do APARELHO) no redirect de /api/phone/session para `/`.
            # Esse token não é de TV: vale o cookie de sessão que acabou de ser criado, em vez de responder 401 JSON na página.
            if not dev and phone_token_valid(conn, token):
                token = None
            prof = profile_of(conn, dev["user_id"], request.headers.get("X-Profile")) if dev and request.headers.get("X-Profile") else None
    if token is not None:  # 40.4: TV — o token vale no lugar do cookie (e do cookie nada é gravado)
        if not dev:
            return jerr("err.token_invalido", 401)
        if request.headers.get("X-Profile") and not prof:
            return jerr("err.perfil_invalido", 403)
        session.clear()
        session["user_id"], session["sv"] = dev["user_id"], dev["session_ver"] or 0
        if prof:
            session["profile_id"] = prof["id"]
        g.tv_device = dev["id"]
    if "user_id" not in session:
        return unauthorized()
    with get_db() as conn:
        user = conn.execute("SELECT session_ver FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        prof = conn.execute(
            "SELECT 1 FROM profiles WHERE id = ? AND user_id = ?", (session.get("profile_id"), session["user_id"])
        ).fetchone()
    if not user or (user["session_ver"] or 0) != session.get("sv", 0):  # removido ou encerrado após troca de senha
        session.clear()
        return unauthorized()
    if session.get("phone_id"):  # 58.6: sessão aberta por um celular conectado; revogado = logout
        with get_db() as conn:
            alive = phone_alive(conn, session["phone_id"])
        if not alive:
            session.clear()
            return unauthorized()
    if not prof:
        session.pop("profile_id", None)
    if ep is None:  # URL inexistente: deixa o Flask devolver 404
        return None
    if "profile_id" not in session and not (ep.startswith("profiles.") or ep.startswith("tv_auth.") or ep.startswith("phone_auth.") or ep == "tv_api.profiles" or ep == "account.pavatar" or ep == "auth.logout"):
        if g.get("tv_device"):
            return jerr("err.perfil_nao_escolhido", 400)
        return redirect("/profiles")


@app.after_request
def no_cache_html(resp):
    """HTML sempre revalidado: ao voltar do player a página mostra progresso/assistido atual."""
    if resp.mimetype == "text/html":
        resp.headers["Cache-Control"] = "no-cache"
    return resp


_ERR = {400: "400", 403: "403", 404: "404", 405: "405", 429: "429"}  # chaves page.err.<código>.title / .msg


@app.errorhandler(Exception)
def friendly_error(e):
    """Erros em páginas (navegação do navegador ou do WebView do app) viram uma página do StarFlix, nunca JSON/texto cru. Chamadas de API (fetch,
    player, imagens) seguem como antes: HTTP padrão, ou JSON `{error}` quando for falha inesperada."""
    code = e.code if isinstance(e, HTTPException) and e.code else 500
    if isinstance(e, HTTPException) and code < 400:
        return e  # redirecionamentos
    if not isinstance(e, HTTPException):
        app.logger.exception("Erro não tratado em %s %s", request.method, request.path)
    html = request.method == "GET" and "text/html" in request.headers.get("Accept", "") and not request.path.startswith(("/api/", "/stream/", "/static/"))
    if html:
        k = "page.err." + _ERR.get(code, "500")
        return render_template("error.html", title=i18n.tr(k + ".title"), msg=i18n.tr(k + ".msg")), code
    return (e if isinstance(e, HTTPException) else jerr("err.erro_interno", 500))


@app.url_defaults
def static_version(endpoint, values):
    """Cache-busting: /static/...?v=<mtime>; o navegador nunca fica com JS/CSS antigo depois de atualizar."""
    if endpoint == "static" and "filename" in values and "v" not in values:
        try:
            values["v"] = int(os.path.getmtime(os.path.join(app.static_folder, values["filename"])))
        except OSError:
            pass


@app.route("/health")
def health():
    return jsonify(status="ok")


@app.template_global("dtitle")
def _dtitle(m):
    """Título exibido de uma linha de media (28.5: original quando a biblioteca pede)."""
    return display_title(m["library_id"], m["title"], m["original_title"])


app.add_template_global(i18n.tr, "t")  # 59.2: {{ t('chave', n=3) }} e {{ _('chave') }} (em laços com variável `t`, use `_`)
app.add_template_global(i18n.tr, "_")


@app.context_processor
def i18n_context():
    return {"ui_lang": i18n.current_lang(), "i18n_langs": i18n.LANGS}


@app.context_processor
def nav_context():
    """Dados da barra lateral (bibliotecas liberadas, admin, perfil) para templates que herdam base.html."""
    if "user_id" not in session:
        return {}
    with get_db() as conn:
        u = conn.execute("SELECT is_admin, avatar, username, full_name FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        p = conn.execute("SELECT id, name, avatar, photo FROM profiles WHERE id = ?", (session.get("profile_id"),)).fetchone()
    up = user_prefs(session["user_id"])
    return {
        "nav_seen": up["seen"],
        "nav_libraries": pinned_libraries(session["user_id"]),
        "nav_is_admin": bool(u and u["is_admin"]),
        "nav_user_avatar": profile_photo_url(p["id"], p["photo"]) if p and p["photo"] else None,
        "nav_pid": p["id"] if p else None,
        "nav_username": u["username"] if u else "",
        "nav_full_name": p["name"] if p else "",
        "nav_profile": p["name"] if p else None,
        "nav_avatar": p["avatar"] if p and re.fullmatch(r"#[0-9a-fA-F]{6}", p["avatar"] or "") else None,
    }


@app.route("/")
@login_required
def index():
    with get_db() as conn:
        user = conn.execute("SELECT username FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        prof = conn.execute("SELECT name FROM profiles WHERE id = ?", (session["profile_id"],)).fetchone()
    if not user or not prof:
        session.clear()
        return redirect("/login")
    from server.home_rows import build_rows_cached
    rows = build_rows_cached(session["user_id"], session["profile_id"], fresh=True)  # 32.8: fileiras do motor (32.3)
    from server.home_rows import hero_items
    # 54.8: no celular o Continuar assistindo (se tiver itens) é sempre a 1ª fileira fixa
    # 54.12: o destaque são os adicionados mais recentemente entre filmes e séries (não depende das fileiras)
    from server.home_library import hero_recent
    try:
        hero = hero_items({"type": "poster", "items": hero_recent(session["user_id"], session["profile_id"])})
    except Exception:  # sem destaque o Início continua normal
        hero = []
    return render_template("home.html", rows=rows, hero=hero, hero_key=None, server_name="StarFlix")


if __name__ == "__main__":
    config.RESTART_ON_PORT = True  # 60.1: trocar a porta em Configurações → Servidor reinicia este processo
    start_periodic(config.SCAN_INTERVAL)
    start_cleanup()
    start_discovery()  # 58.3: anúncio mDNS (falha em silêncio)
    from waitress import serve

    serve(app, host="0.0.0.0", port=config.PORT, threads=config.THREADS)
