"""58.1: Configurações → Servidor (/admin/server): nome, endereço externo (que os apps usam fora de casa), endereços locais
detectados e interruptor do mDNS (58.3). Valores em `settings`: server_name, server_url, server_id (uuid estável, nasce na 1ª
leitura) e mdns_enabled."""
import ipaddress
import re
import socket
import subprocess
import time
import uuid
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, render_template, request

import config
from server.auth import admin_required
from server import i18n
from server.i18n import E, jerr
from server.db import get_db
from server.libraries import get_setting
from server.tv_auth import rate_ok

bp = Blueprint("admin_server", __name__)

NAME_DEFAULT = "StarFlix"
NAME_MAX = 60
_HOST_RE = re.compile(r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$")
_SKIP_IFACE = ("lo", "docker", "br-", "veth", "virbr")


def _upsert(conn, key, value):
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def get_server_id(conn):
    """Identificador estável deste servidor (os apps o usam para reconhecê-lo em qualquer endereço)."""
    sid = get_setting(conn, "server_id")
    if not sid:
        conn.execute("INSERT INTO settings (key, value) VALUES ('server_id', ?) ON CONFLICT(key) DO NOTHING", (uuid.uuid4().hex,))
        conn.commit()
        sid = get_setting(conn, "server_id")
    return sid


def get_server_name(conn):
    return (get_setting(conn, "server_name", "") or "").strip()[:NAME_MAX] or NAME_DEFAULT


def get_server_url(conn):
    return get_setting(conn, "server_url", "") or ""


def mdns_enabled(conn):
    return get_setting(conn, "mdns_enabled", "1") != "0"


def default_lang(conn):
    """59.2: idioma padrão do servidor (settings.default_lang); vale quando o usuário não escolheu e o navegador não pede um idioma suportado."""
    return i18n.norm(get_setting(conn, "default_lang", "")) or i18n.DEFAULT


def public_base(conn):
    """Endereço que vai nos QR/links (58.5): o externo configurado; sem ele, o que o navegador usou para chegar aqui."""
    return get_server_url(conn) or request.host_url.rstrip("/")


def is_private_host(host):
    h = (host or "").lower().strip("[]")
    if h == "localhost" or h.endswith((".local", ".lan")):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def normalize_url(raw):
    """Endereço digitado → (url normalizada, None) ou (None, erro). Vazio = ("", None).
    Aceita https/http, domínio ou IP, `:porta` opcional; sem esquema segue a regra do app (57.9): IP, localhost, .local/.lan ou
    com porta = http; domínio sem porta = https. Só a origem (sem caminho); tira a `/` final e a porta padrão."""
    s = (raw or "").strip() if isinstance(raw, str) else ""
    if not s:
        return "", None
    if len(s) > 200:
        return None, E("err.endereco_muito_longo")
    explicit = "://" in s
    try:
        p = urlsplit(s if explicit else "//" + s)
        host, port = p.hostname, p.port
    except ValueError:
        return None, E("err.endereco_invalido")
    if explicit and p.scheme not in ("http", "https"):
        return None, E("err.use_http_ou_https")
    if p.path not in ("", "/") or p.query or p.fragment or p.username or p.password:
        return None, E("err.use_so_endereco_sem_caminho")
    if not host:
        return None, E("err.endereco_invalido")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not _HOST_RE.match(host):
            return None, E("err.endereco_invalido")
    if port is not None and not 1 <= port <= 65535:
        return None, E("err.porta_invalida")
    scheme = p.scheme if explicit else ("http" if (port is not None or is_private_host(host)) else "https")
    netloc = f"[{host}]" if ":" in host else host
    if port is not None and port != (443 if scheme == "https" else 80):
        netloc += f":{port}"
    return f"{scheme}://{netloc}", None


def local_addresses():
    """Endereços da máquina na rede local (IPv4, sem loopback/link-local/docker), já com a porta: `http://IP:32000`."""
    found = []
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr", "show"], capture_output=True, text=True, timeout=2).stdout
        for line in out.splitlines():
            t = line.split()
            if len(t) >= 4 and t[2] == "inet":
                found.append((t[1], t[3].split("/")[0]))
    except (OSError, subprocess.SubprocessError):
        pass
    if not found:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.255.255.255", 1))
            found.append(("", s.getsockname()[0]))
            s.close()
        except OSError:
            pass
        try:
            found += [("", ip) for ip in socket.gethostbyname_ex(socket.gethostname())[2]]
        except OSError:
            pass
    res = []
    for iface, ip in found:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if a.is_loopback or a.is_link_local or iface.startswith(_SKIP_IFACE):
            continue
        u = f"http://{ip}:{config.PORT}"
        if u not in res:
            res.append(u)
    return res


def _warning(url):
    if url and is_private_host(urlsplit(url).hostname):
        return E("sv.warn_local")
    if not url:
        host = request.host.rsplit(":", 1)[0] if not request.host.startswith("[") else request.host.split("]")[0].strip("[")
        if is_private_host(host):
            return E("sv.warn_none")
    return ""


def _payload(conn):
    url = get_server_url(conn)
    return {"name": get_server_name(conn), "url": url, "id": get_server_id(conn), "mdns": mdns_enabled(conn), "lang": default_lang(conn),
            "port": config.PORT, "local": local_addresses(), "request_url": request.host_url.rstrip("/"), "warning": _warning(url), "brand": __import__("server.branding", fromlist=["x"]).admin_state(conn)}


@bp.route("/admin/server")
@admin_required
def page():
    return render_template("admin_server.html")


@bp.route("/admin/server/data")
@admin_required
def data():
    with get_db() as conn:
        return jsonify(_payload(conn))


@bp.route("/admin/server/normalize", methods=["POST"])
@admin_required
def normalize():
    d = request.get_json(silent=True)
    url, err = normalize_url(d.get("url") if isinstance(d, dict) else None)
    if err:
        return jerr(err, 400)
    return jsonify(url=url)


@bp.route("/admin/server/save", methods=["POST"])
@admin_required
def save():
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return jerr("err.dados_invalidos", 400)
    with get_db() as conn:
        cur = _payload(conn)
    name = d.get("name", cur["name"])
    mdns = d.get("mdns", cur["mdns"])
    lang = d.get("lang", cur["lang"])
    if not isinstance(name, str) or len(name.strip()) > NAME_MAX or not isinstance(mdns, bool) or lang not in i18n.CODES:
        return jerr("err.opcao_invalida", 400)
    url, err = normalize_url(d["url"]) if "url" in d else (cur["url"], None)  # ausente = mantém o atual
    if err:
        return jerr(err, 400)
    with get_db() as conn:
        _upsert(conn, "server_name", name.strip() or NAME_DEFAULT)
        _upsert(conn, "server_url", url)
        _upsert(conn, "mdns_enabled", "1" if mdns else "0")
        _upsert(conn, "default_lang", lang)
        conn.commit()
        out = _payload(conn)
    from server import discovery  # 58.3: import tardio (discovery importa este módulo)
    discovery.refresh_async()
    return jsonify(out)


_local_cache = [0.0, []]  # [instante, lista]: `ip` não roda a cada consulta dos apps


def _local_cached():
    if time.time() - _local_cache[0] > 30:
        _local_cache[:] = [time.time(), local_addresses()]
    return _local_cache[1]


@bp.route("/api/server-info")
def info():
    """58.2: pública (os apps ainda não têm sessão). Só o que o app precisa para reconhecer o servidor e escolher o endereço:
    {app, id, name, version, port, urls:{external, local:[...]}, mdns}. CORS aberto para o botão Testar de /admin/server."""
    if not rate_ok("srv-info", request.remote_addr or "?", 60, 60):
        return jerr("err.muitos_pedidos_tente_novo_instantes", 429)
    with get_db() as conn:
        r = jsonify(app="starflix", id=get_server_id(conn), name=get_server_name(conn), version=config.VERSION, port=config.PORT,
                    urls={"external": get_server_url(conn), "local": _local_cached()}, mdns=mdns_enabled(conn))
    r.headers["Access-Control-Allow-Origin"] = "*"
    return r
