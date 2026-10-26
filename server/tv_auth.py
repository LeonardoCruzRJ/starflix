"""40.2: pareamento da TV. A TV pede um código (POST /api/tv/code), mostra QR + código e consulta (GET /api/tv/code/<poll>) até o usuário
autorizar em /tv (40.3); só então recebe o token, uma única vez. Rotas públicas (a TV ainda não tem sessão)."""
import hashlib
import secrets
import sqlite3
import threading
import time


from flask import Blueprint, g, jsonify, render_template, request, session

from server.auth import admin_required, login_required
from server.db import get_db
from server import i18n
from server.i18n import E, jerr

bp = Blueprint("tv_auth", __name__)

CODE_LEN = 6
CODE_TTL = 600  # s: o código vale 10 min
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # sem 0/O/1/I/L
NAME_MAX = 40

_hits = {}  # (balde, ip) -> [instantes]
_hits_lock = threading.Lock()


def rate_ok(bucket, ip, limit, window):
    """Limite por IP em memória: no máximo `limit` chamadas a cada `window` s no balde `bucket` (reaproveitado pela página /tv, 40.3)."""
    now = time.time()
    with _hits_lock:
        h = [t for t in _hits.get((bucket, ip), []) if now - t < window]
        if len(h) >= limit:
            _hits[(bucket, ip)] = h
            return False
        h.append(now)
        _hits[(bucket, ip)] = h
        if len(_hits) > 2000:  # não deixa a tabela crescer sem fim
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > 3600]:
                _hits.pop(k, None)
    return True


def too_many(bucket, ip, limit, window):
    """Já passou do limite? (só consulta; `hit` registra uma ocorrência, usada para contar só as tentativas que falham)."""
    now = time.time()
    with _hits_lock:
        return len([t for t in _hits.get((bucket, ip), []) if now - t < window]) >= limit


def hit(bucket, ip):
    with _hits_lock:
        _hits.setdefault((bucket, ip), []).append(time.time())


def new_code():
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))


def norm_code(s):
    """Código digitado: só letras/números, maiúsculas, sem espaços e hífens."""
    return "".join(ch for ch in str(s or "").upper() if ch.isalnum())


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_tv_device(conn, user_id, name, now):
    """Cria o aparelho da TV e devolve (token, id); só o hash fica no banco (usada pelo pareamento por código e pelo ticket do celular, 58.7)."""
    token = secrets.token_urlsafe(32)
    cur = conn.execute("INSERT INTO tv_devices (user_id, name, token_hash, created_at, last_seen) VALUES (?, ?, ?, ?, ?)",
                       (user_id, name, token_hash(token), now, now))
    return token, cur.lastrowid


@bp.route("/api/tv/code", methods=["POST"])
def code_new():
    """A TV pede um código de pareamento. Corpo opcional: {name}. Devolve {code, poll, url, expires_in}."""
    ip = request.remote_addr or "?"
    if not rate_ok("tv-new", ip, 10, 600):
        return jerr("err.muitos_pedidos_tente_novo_alguns", 429)
    d = request.get_json(silent=True)
    name = " ".join(str((d or {}).get("name") or "").split())[:NAME_MAX] if isinstance(d, dict) else ""
    name = name or "TV"
    now = int(time.time())
    with get_db() as conn:
        for _ in range(20):  # colisão de código é rara; tenta outro
            code, poll = new_code(), secrets.token_urlsafe(24)
            try:
                conn.execute("INSERT INTO tv_codes (code, poll, device_name, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                             (code, poll, name, now, now + CODE_TTL))
                break
            except sqlite3.IntegrityError:
                continue
        else:
            return jerr("err.nao_foi_possivel_gerar_codigo", 500)
    # 57.9: atrás de proxy https (nginx, Caddy…) o endereço público vem nos cabeçalhos X-Forwarded-*
    proto = (request.headers.get("X-Forwarded-Proto") or request.scheme).split(",")[0].strip()
    host = (request.headers.get("X-Forwarded-Host") or request.host).split(",")[0].strip()
    return jsonify(code=code, poll=poll, url=f"{proto}://{host}/tv", expires_in=CODE_TTL)


@bp.route("/api/tv/code/<poll>")
def code_poll(poll):
    """A TV consulta o pareamento: 200 `pending` | 200 `authorized` + `token` (uma única vez) | 410 `expired` ou `used` | 404."""
    ip = request.remote_addr or "?"
    now = int(time.time())
    with get_db() as conn:
        r = conn.execute("SELECT code, device_name, expires_at, user_id, used FROM tv_codes WHERE poll = ?", (poll,)).fetchone()
        if not r:
            if not rate_ok("tv-poll404", ip, 30, 60):
                return jerr("err.muitas_tentativas", 429)
            return jerr("err.codigo_nao_encontrado", 404, status="unknown")
        if r["used"]:
            return jerr("err.este_codigo_ja_foi_usado", 410, status="used")
        if r["user_id"] is None:
            if now >= r["expires_at"]:
                return jerr("err.codigo_vencido", 410, status="expired")
            return jsonify(status="pending", expires_in=r["expires_at"] - now)
        # autorizado: marca como usado e cria o token (só o hash fica no banco); quem marcar primeiro leva o token
        if conn.execute("UPDATE tv_codes SET used = 1 WHERE poll = ? AND used = 0 AND user_id IS NOT NULL", (poll,)).rowcount != 1:
            return jerr("err.este_codigo_ja_foi_usado", 410, status="used")
        token, did = create_tv_device(conn, r["user_id"], r["device_name"], now)
        return jsonify(status="authorized", token=token, device_id=did, name=r["device_name"])


# ---- 40.3: página /tv (autorizar uma TV pelo código ou pelo QR, listar e revogar) ----
FAIL_LIMIT, FAIL_WINDOW = 10, 600  # tentativas erradas por IP


def authorize_code(conn, code, user_id, ip):
    """Liga o código ao usuário. Devolve (True, nome do aparelho) ou (False, mensagem). Só conta as tentativas que falham."""
    if too_many("tv-auth-fail", ip, FAIL_LIMIT, FAIL_WINDOW):
        return False, E("err.muitas_tentativas_erradas")
    code, now = norm_code(code), int(time.time())
    r = conn.execute("SELECT device_name FROM tv_codes WHERE code = ? AND used = 0 AND user_id IS NULL AND expires_at > ?", (code, now)).fetchone() \
        if len(code) == CODE_LEN else None
    if r and conn.execute("UPDATE tv_codes SET user_id = ? WHERE code = ? AND used = 0 AND user_id IS NULL AND expires_at > ?",
                          (user_id, code, now)).rowcount == 1:
        return True, r["device_name"]
    hit("tv-auth-fail", ip)
    return False, E("err.codigo_invalido_ou_vencido_confira")


def _stamp(t):
    return i18n.fmt_stamp(t)


def devices_of(conn, user_id):
    return [{"id": d["id"], "name": d["name"], "created": _stamp(d["created_at"]), "seen": _stamp(d["last_seen"])}
            for d in conn.execute("SELECT id, name, created_at, last_seen FROM tv_devices WHERE user_id = ? ORDER BY created_at DESC, id DESC", (user_id,))]


def _from_user_navigation():
    """O QR abre o navegador direto (Sec-Fetch-Site: none); link vindo de outro site não autoriza sozinho (só preenche o código)."""
    return request.headers.get("Sec-Fetch-Site", "none") in ("none", "same-origin")


@bp.route("/tv")
def page():
    """Página para o usuário logado autorizar a TV. `/tv?code=XXXXXX` (QR) autoriza sozinho e mostra o resultado."""
    uid = session["user_id"]
    code = norm_code(request.args.get("code"))[:CODE_LEN]
    result = None
    with get_db() as conn:
        if len(code) == CODE_LEN and _from_user_navigation():
            ok, info = authorize_code(conn, code, uid, request.remote_addr or "?")
            result = {"ok": ok, "text": f"TV autorizada: {info}. Ela entra em alguns segundos." if ok else info}
            if ok:
                code = ""
        devices = devices_of(conn, uid)
    return render_template("tv.html", code=code, result=result, devices=devices, has_profile="profile_id" in session)


@bp.route("/tv/authorize", methods=["POST"])
def authorize():
    d = request.get_json(silent=True)
    with get_db() as conn:
        ok, info = authorize_code(conn, d.get("code") if isinstance(d, dict) else "", session["user_id"], request.remote_addr or "?")
    if not ok:
        return jerr(info, 429 if getattr(info, "key", "") == "err.muitas_tentativas_erradas" else 400)
    return jsonify(ok=True, name=info)


@bp.route("/tv/devices")
def devices():
    with get_db() as conn:
        return jsonify(devices=devices_of(conn, session["user_id"]))


@bp.route("/tv/devices/<int:did>/revoke", methods=["POST"])
def revoke(did):
    """Revoga uma TV do próprio usuário (o token deixa de valer na hora). O admin revoga as dos outros em /admin/users (40.4)."""
    with get_db() as conn:
        n = conn.execute("DELETE FROM tv_devices WHERE id = ? AND user_id = ?", (did, session["user_id"])).rowcount
    return (jsonify(ok=True), 200) if n else jerr("err.tv_nao_encontrada", 404)


# ---- 40.4: autenticação por token (Bearer) e perfil da TV ----
SEEN_EVERY = 60  # s: `last_seen` só é regravado a cada minuto


def bearer_token():
    """Token do cabeçalho `Authorization: Bearer <token>`; None se o cabeçalho não existe."""
    h = request.headers.get("Authorization", "")
    return h[7:].strip() if h[:7].lower() == "bearer " else None


def device_for_token(conn, token):
    """Aparelho do token (só o hash fica no banco) com o `session_ver` do usuário; None se inválido ou revogado. Atualiza `last_seen`."""
    d = conn.execute("SELECT d.id, d.user_id, d.last_seen, u.session_ver FROM tv_devices d JOIN users u ON u.id = d.user_id WHERE d.token_hash = ?",
                     (token_hash(token),)).fetchone() if token else None
    now = int(time.time())
    if d and now - (d["last_seen"] or 0) >= SEEN_EVERY:
        conn.execute("UPDATE tv_devices SET last_seen = ? WHERE id = ?", (now, d["id"]))
    return d


def profile_of(conn, user_id, raw):
    """Perfil do cabeçalho `X-Profile` se for do usuário (só `[0-9]+`); None caso contrário."""
    raw = (raw or "").strip()
    if not (raw.isascii() and raw.isdigit()):
        return None
    return conn.execute("SELECT id FROM profiles WHERE id = ? AND user_id = ?", (int(raw), user_id)).fetchone()


@bp.route("/api/tv/profile/<int:pid>", methods=["POST"])
@login_required
def profile_pick(pid):
    """A TV escolhe o perfil: valida que é do usuário do token e devolve os dados; depois a TV manda `X-Profile: <id>` em toda chamada."""
    with get_db() as conn:
        p = conn.execute("SELECT id, name, avatar FROM profiles WHERE id = ? AND user_id = ?", (pid, session["user_id"])).fetchone()
    if not p:
        return jerr("err.perfil_nao_encontrado", 404)
    return jsonify(ok=True, id=p["id"], name=p["name"], avatar=p["avatar"])


@bp.route("/api/tv/logout", methods=["POST"])
@login_required
def tv_logout():
    """A própria TV se desconecta (40.15): apaga o aparelho do token em uso, que deixa de valer na hora."""
    did = g.get("tv_device")
    if not did:
        return jerr("err.so_tvs_conectadas", 400)
    with get_db() as conn:
        conn.execute("DELETE FROM tv_devices WHERE id = ?", (did,))
    return jsonify(ok=True)


@bp.route("/admin/tv/devices")
@admin_required
def admin_devices():
    """Todas as TVs conectadas, de todos os usuários (página /admin/users)."""
    with get_db() as conn:
        rows = [{"id": d["id"], "name": d["name"], "user": d["username"], "created": _stamp(d["created_at"]), "seen": _stamp(d["last_seen"])}
                for d in conn.execute("SELECT d.id, d.name, d.created_at, d.last_seen, u.username FROM tv_devices d JOIN users u ON u.id = d.user_id "
                                      "ORDER BY fold(u.username), d.created_at DESC, d.id DESC")]
    return jsonify(devices=rows)


@bp.route("/admin/tv/devices/<int:did>/revoke", methods=["POST"])
@admin_required
def admin_revoke(did):
    with get_db() as conn:
        n = conn.execute("DELETE FROM tv_devices WHERE id = ?", (did,)).rowcount
    return (jsonify(ok=True), 200) if n else jerr("err.tv_nao_encontrada", 404)
