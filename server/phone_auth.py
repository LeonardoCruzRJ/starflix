"""58.5: conexão do celular (Fase 58). O site gera um QR (60 s) ou um link (24 h), ambos de uso único, com o endereço do servidor;
o app abre `/c/<token>` (ou lê o QR) e troca o token por um token de aparelho em POST /api/phone/claim. Só o hash fica no banco."""
import logging
import secrets
import time
from urllib.parse import quote, urlsplit

from flask import Blueprint, jsonify, redirect, render_template, request, session

from server.admin_server import _local_cached, is_private_host, get_server_id, get_server_name, get_server_url, mdns_enabled, public_base
from server.auth import admin_required, login_required
from server.db import get_db
from server.tv_auth import _stamp, bearer_token, create_tv_device, hit, rate_ok, token_hash, too_many

import config
from server.i18n import jerr

bp = Blueprint("phone_auth", __name__)

QR_TTL = 60  # s
LINK_TTL = 86400  # 24 h
NAME_MAX = 40
FAIL_LIMIT, FAIL_WINDOW = 10, 600  # tentativas erradas de claim/consulta por IP


def _make(kind, ttl):
    """Cria um token de uso único para o usuário logado. Devolve (url, expires_at, id). O QR anterior ainda não usado é invalidado."""
    token, now = secrets.token_urlsafe(24), int(time.time())
    with get_db() as conn:
        if kind == "qr":
            conn.execute("DELETE FROM phone_tokens WHERE user_id = ? AND kind = 'qr' AND used_at IS NULL", (session["user_id"],))
        cur = conn.execute("INSERT INTO phone_tokens (user_id, kind, token_hash, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                           (session["user_id"], kind, token_hash(token), now, now + ttl))
        base = public_base(conn)
    return f"{base}/c/{token}", now + ttl, cur.lastrowid


def _svg(url):
    """QR em SVG (segno); None se a biblioteca não estiver instalada (o site mostra só o link)."""
    try:
        import segno
        return segno.make(url, error="m").svg_inline(scale=6, border=2, dark="#000000", light="#ffffff")
    except Exception as e:
        logging.getLogger(__name__).error("QR do celular: falha ao gerar o SVG (%s: %s). Se for ModuleNotFoundError, instale: sudo python3 -m pip install --break-system-packages segno", type(e).__name__, e)
        return None


@bp.route("/phone")
@login_required
def page():
    """58.8: página Conectar Celular (QR dinâmico, instruções e, na 58.9, link e lista de celulares)."""
    with get_db() as conn:
        u = conn.execute("SELECT is_admin FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    return render_template("phone.html", has_profile="profile_id" in session, is_admin=bool(u and u["is_admin"]))


@bp.route("/phone/token/<int:tid>")
@login_required
def token_status(tid):
    """Estado do QR/link do próprio usuário: pending | used (com o nome do celular) | expired. A página consulta a cada 2 s para renovar o QR na hora."""
    now = int(time.time())
    with get_db() as conn:
        r = conn.execute("SELECT t.used_at, t.expires_at, d.name FROM phone_tokens t LEFT JOIN phone_devices d ON d.id = t.device_id "
                         "WHERE t.id = ? AND t.user_id = ?", (tid, session["user_id"])).fetchone()
    if not r:
        return jsonify(status="expired"), 404
    if r["used_at"] is not None:
        return jsonify(status="used", name=r["name"] or "Celular")
    return jsonify(status="expired" if r["expires_at"] <= now else "pending", expires_in=max(0, r["expires_at"] - now))


@bp.route("/phone/qr", methods=["POST"])
@login_required
def qr_new():
    if not rate_ok("phone-make", str(session["user_id"]), 60, 600):
        return jerr("err.muitos_pedidos_tente_novo_alguns", 429)
    url, exp, tid = _make("qr", QR_TTL)
    return jsonify(id=tid, url=url, svg=_svg(url), expires=exp, expires_in=QR_TTL, local=is_private_host(urlsplit(url).hostname))


@bp.route("/phone/link", methods=["POST"])
@login_required
def link_new():
    if not rate_ok("phone-make", str(session["user_id"]), 60, 600):
        return jerr("err.muitos_pedidos_tente_novo_alguns", 429)
    url, exp, tid = _make("link", LINK_TTL)
    return jsonify(id=tid, url=url, expires=exp, expires_in=LINK_TTL)


@bp.route("/c/<token>")
def connect_page(token):
    """Página aberta pelo link/QR. Não consome o token: só mostra o botão que abre o app (e instruções se ele não estiver instalado)."""
    ip = request.remote_addr or "?"
    if too_many("phone-fail", ip, FAIL_LIMIT, FAIL_WINDOW):
        return render_template("phone_connect.html", state="limit"), 429
    now = int(time.time())
    with get_db() as conn:
        r = conn.execute("SELECT 1 FROM phone_tokens WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?", (token_hash(token), now)).fetchone()
        base = public_base(conn)
        name = get_server_name(conn)
    if not r:
        hit("phone-fail", ip)
        return render_template("phone_connect.html", state="invalid"), 410
    deep = f"starflix://connect?u={quote(base, safe='')}&t={quote(token, safe='')}"
    return render_template("phone_connect.html", state="ok", deep=deep, server=name, base=base)


@bp.route("/api/phone/claim", methods=["POST"])
def claim():
    """O app troca o token do QR/link por um token de aparelho (devolvido uma única vez; só o hash fica). Corpo: {token, name}."""
    ip = request.remote_addr or "?"
    if too_many("phone-fail", ip, FAIL_LIMIT, FAIL_WINDOW):
        return jerr("err.muitas_tentativas_aguarde_alguns_minutos", 429)
    d = request.get_json(silent=True)
    d = d if isinstance(d, dict) else {}
    token = str(d.get("token") or "").strip()
    name = (" ".join(str(d.get("name") or "").split())[:NAME_MAX]) or "Celular"
    now = int(time.time())
    with get_db() as conn:
        r = conn.execute("SELECT id, user_id, used_at, expires_at FROM phone_tokens WHERE token_hash = ?", (token_hash(token),)).fetchone() if token else None
        if not r:
            hit("phone-fail", ip)
            return jerr("err.link_ou_qr_invalido", 404, status="unknown")
        if r["used_at"] is not None or r["expires_at"] <= now:
            hit("phone-fail", ip)
            return jerr("err.este_qr_ou_link_ja", 410, status="expired")
        # quem marcar primeiro leva o aparelho
        if conn.execute("UPDATE phone_tokens SET used_at = ? WHERE id = ? AND used_at IS NULL AND expires_at > ?", (now, r["id"], now)).rowcount != 1:
            return jerr("err.este_qr_ou_link_ja", 410, status="expired")
        device_token = secrets.token_urlsafe(32)
        cur = conn.execute("INSERT INTO phone_devices (user_id, name, token_hash, created_at, last_seen) VALUES (?, ?, ?, ?, ?)",
                           (r["user_id"], name, token_hash(device_token), now, now))
        conn.execute("UPDATE phone_tokens SET device_id = ? WHERE id = ?", (cur.lastrowid, r["id"]))
        info = {"app": "starflix", "id": get_server_id(conn), "name": get_server_name(conn), "version": config.VERSION, "port": config.PORT,
                "urls": {"external": get_server_url(conn), "local": _local_cached()}, "mdns": mdns_enabled(conn)}
    return jsonify(status="authorized", device_token=device_token, device_id=cur.lastrowid, name=name, server=info)


# ---- 58.6: sessão por token do aparelho, revogação e listas ----
SEEN_EVERY = 60  # s: `last_seen` só é regravado a cada minuto


@bp.route("/api/phone/session")
def session_from_token():
    """O app (WebView) troca o token do aparelho (`Authorization: Bearer`) por um cookie de sessão na origem atual e vai para `/`.
    Pública no `gate` (o token de celular não é o da TV); token inválido ou revogado = 401 JSON."""
    ip = request.remote_addr or "?"
    token = bearer_token()
    if too_many("phone-fail", ip, FAIL_LIMIT, FAIL_WINDOW):
        return jerr("err.muitas_tentativas_aguarde_alguns_minutos", 429)
    with get_db() as conn:
        d = conn.execute("SELECT d.id, d.user_id, u.session_ver FROM phone_devices d JOIN users u ON u.id = d.user_id WHERE d.token_hash = ?",
                         (token_hash(token),)).fetchone() if token else None
        if not d:
            hit("phone-fail", ip)
            return jerr("err.aparelho_nao_autorizado_ou_revogado", 401)
        conn.execute("UPDATE phone_devices SET last_seen = ? WHERE id = ?", (int(time.time()), d["id"]))
    session.clear()
    session["user_id"], session["sv"], session["phone_id"] = d["user_id"], d["session_ver"] or 0, d["id"]
    session.permanent = True
    return redirect("/")


def phone_alive(conn, phone_id):
    """Usado pelo `gate`: o aparelho da sessão ainda existe? (revogado = logout). Atualiza `last_seen` a cada minuto."""
    r = conn.execute("SELECT last_seen FROM phone_devices WHERE id = ?", (phone_id,)).fetchone()
    if not r:
        return False
    now = int(time.time())
    if now - (r["last_seen"] or 0) >= SEEN_EVERY:
        conn.execute("UPDATE phone_devices SET last_seen = ? WHERE id = ?", (now, phone_id))
    return True


def phone_token_valid(conn, token):
    """O token (Bearer) é de um celular conectado e não revogado? Só consulta (não atualiza nada)."""
    return bool(token) and conn.execute("SELECT 1 FROM phone_devices WHERE token_hash = ?", (token_hash(token),)).fetchone() is not None


@bp.route("/phone/devices")
@login_required
def devices():
    with get_db() as conn:
        rows = [{"id": d["id"], "name": d["name"], "created": _stamp(d["created_at"]), "seen": _stamp(d["last_seen"])}
                for d in conn.execute("SELECT id, name, created_at, last_seen FROM phone_devices WHERE user_id = ? ORDER BY created_at DESC, id DESC",
                                      (session["user_id"],))]
    return jsonify(devices=rows)


@bp.route("/phone/devices/<int:did>/revoke", methods=["POST"])
@login_required
def revoke(did):
    """Revoga um celular do próprio usuário (a sessão dele cai na próxima chamada). O admin revoga os dos outros em /admin/phone/devices."""
    with get_db() as conn:
        n = conn.execute("DELETE FROM phone_devices WHERE id = ? AND user_id = ?", (did, session["user_id"])).rowcount
    return (jsonify(ok=True), 200) if n else jerr("err.celular_nao_encontrado", 404)


@bp.route("/admin/phone/devices")
@admin_required
def admin_devices():
    with get_db() as conn:
        rows = [{"id": d["id"], "name": d["name"], "user": d["username"], "created": _stamp(d["created_at"]), "seen": _stamp(d["last_seen"])}
                for d in conn.execute("SELECT d.id, d.name, d.created_at, d.last_seen, u.username FROM phone_devices d JOIN users u ON u.id = d.user_id "
                                      "ORDER BY fold(u.username), d.created_at DESC, d.id DESC")]
    return jsonify(devices=rows)


@bp.route("/admin/phone/devices/<int:did>/revoke", methods=["POST"])
@admin_required
def admin_revoke(did):
    with get_db() as conn:
        n = conn.execute("DELETE FROM phone_devices WHERE id = ?", (did,)).rowcount
    return (jsonify(ok=True), 200) if n else jerr("err.celular_nao_encontrado", 404)


# ---- 58.7: ticket da TV (o celular conectado autoriza a TV sem digitar nada) ----
TICKET_TTL = 300  # s: 5 min


@bp.route("/api/phone/tv-ticket", methods=["POST"])
def tv_ticket():
    """O app do celular (Bearer do aparelho) pede um ticket de uso único para entregar à TV. Pública no `gate`; valida o token aqui."""
    ip = request.remote_addr or "?"
    token = bearer_token()
    if too_many("phone-fail", ip, FAIL_LIMIT, FAIL_WINDOW):
        return jerr("err.muitas_tentativas_aguarde_alguns_minutos", 429)
    now = int(time.time())
    with get_db() as conn:
        d = conn.execute("SELECT id, user_id FROM phone_devices WHERE token_hash = ?", (token_hash(token),)).fetchone() if token else None
        if not d:
            hit("phone-fail", ip)
            return jerr("err.aparelho_nao_autorizado_ou_revogado", 401)
        if not rate_ok("tv-ticket", str(d["id"]), 20, 600):
            return jerr("err.muitos_pedidos_tente_novo_alguns", 429)
        conn.execute("UPDATE phone_devices SET last_seen = ? WHERE id = ?", (now, d["id"]))
        ticket = secrets.token_urlsafe(24)
        conn.execute("INSERT INTO tv_tickets (user_id, token_hash, created_at, expires_at) VALUES (?, ?, ?, ?)",
                     (d["user_id"], token_hash(ticket), now, now + TICKET_TTL))
    return jsonify(ticket=ticket, expires_in=TICKET_TTL)


@bp.route("/api/phone/me")
def phone_me():
    """58.16: nome da conta do aparelho (Bearer), para o modal \"Conectar a TV … à conta …\" do app. Pública no `gate`; valida o token aqui."""
    ip = request.remote_addr or "?"
    token = bearer_token()
    if too_many("phone-fail", ip, FAIL_LIMIT, FAIL_WINDOW):
        return jerr("err.muitas_tentativas_aguarde_alguns_minutos", 429)
    with get_db() as conn:
        d = conn.execute("SELECT u.username, u.full_name FROM phone_devices d JOIN users u ON u.id = d.user_id WHERE d.token_hash = ?",
                         (token_hash(token),)).fetchone() if token else None
    if not d:
        hit("phone-fail", ip)
        return jerr("err.aparelho_nao_autorizado_ou_revogado", 401)
    return jsonify(user=d["full_name"] or d["username"])


@bp.route("/api/tv/claim", methods=["POST"])
def tv_claim():
    """A TV troca o ticket (recebido do celular) por um token de TV, como no pareamento por código: devolvido uma única vez, só o hash fica.
    Corpo: {ticket, name}. Pública (a TV ainda não tem sessão), com limite por IP."""
    ip = request.remote_addr or "?"
    if too_many("tv-claim-fail", ip, FAIL_LIMIT, FAIL_WINDOW):
        return jerr("err.muitas_tentativas_aguarde_alguns_minutos", 429)
    d = request.get_json(silent=True)
    d = d if isinstance(d, dict) else {}
    ticket = str(d.get("ticket") or "").strip()
    name = (" ".join(str(d.get("name") or "").split())[:NAME_MAX]) or "TV"
    now = int(time.time())
    with get_db() as conn:
        r = conn.execute("SELECT id, user_id, used_at, expires_at FROM tv_tickets WHERE token_hash = ?", (token_hash(ticket),)).fetchone() if ticket else None
        if not r:
            hit("tv-claim-fail", ip)
            return jerr("err.ticket_invalido", 404, status="unknown")
        if r["used_at"] is not None or r["expires_at"] <= now:
            hit("tv-claim-fail", ip)
            return jerr("err.ticket_ja_usado_ou_vencido", 410, status="expired")
        if conn.execute("UPDATE tv_tickets SET used_at = ? WHERE id = ? AND used_at IS NULL AND expires_at > ?", (now, r["id"], now)).rowcount != 1:
            return jerr("err.ticket_ja_usado_ou_vencido", 410, status="expired")
        token, did = create_tv_device(conn, r["user_id"], name, now)
    return jsonify(status="authorized", token=token, device_id=did, name=name)
