"""67.1: token de transmissão (Google Cast). A TV/Chromecast busca vídeo, legendas e capas por URL, sem cookie nem cabeçalho: o app do celular pede
um token em `POST /api/cast/token` e o acrescenta como `?ct=` nas URLs. Formato `<usuário>.<perfil>.<validade>.<assinatura>` (HMAC-SHA256 com a chave
secreta do servidor), vale 12 h. Só serve em `GET`/`HEAD`/`OPTIONS` das rotas de `CAST_EPS` (conferidas em `gate()` de run.py); trocar a senha
(`session_ver`) ou apagar o perfil invalida na hora. Nunca substitui o login em outras rotas."""
import hashlib
import hmac
import time

from flask import Blueprint, current_app, jsonify, session

from server.auth import login_required
from server.db import get_db

bp = Blueprint("cast", __name__, url_prefix="/api/cast")

TTL = 12 * 3600
CAST_EPS = frozenset({"stream.direct", "stream.hls_file", "subtitles.subs_file", "subtitles.subs_embedded",
                      "libraries.poster", "images.backdrop", "images.still", "images.logo"})


def _sig(uid, pid, exp):
    key = current_app.secret_key
    key = key.encode("utf-8") if isinstance(key, str) else key
    return hmac.new(key, f"cast|{uid}|{pid}|{exp}".encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def make(uid, pid, now=None):
    """(token, segundos de validade)."""
    now = int(time.time() if now is None else now)
    exp, pid = now + TTL, int(pid or 0)
    return f"{uid}.{pid}.{exp}.{_sig(uid, pid, exp)}", TTL


def resolve(conn, tok, now=None):
    """{user_id, session_ver, profile_id} ou None (assinatura errada, vencido, usuário/perfil sumiu)."""
    parts = str(tok or "").split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts[:3]) or len(tok) > 200:
        return None
    uid, pid, exp = (int(p) for p in parts[:3])
    if int(time.time() if now is None else now) >= exp or not hmac.compare_digest(parts[3], _sig(uid, pid, exp)):
        return None
    u = conn.execute("SELECT session_ver FROM users WHERE id = ?", (uid,)).fetchone()
    if not u:
        return None
    if pid and not conn.execute("SELECT 1 FROM profiles WHERE id = ? AND user_id = ?", (pid, uid)).fetchone():
        return None
    return {"user_id": uid, "session_ver": u["session_ver"] or 0, "profile_id": pid or None}


@bp.route("/token", methods=["POST"])
@login_required
def token():
    """Token de transmissão do usuário/perfil em uso."""
    tok, ttl = make(session["user_id"], session.get("profile_id") or 0)
    return jsonify(token=tok, ttl=ttl)
