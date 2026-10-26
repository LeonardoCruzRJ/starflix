"""58.1: Configurações → Servidor (/admin/server): nome, endereço externo (que os apps usam fora de casa), porta (60.1), endereços locais
detectados e interruptor do mDNS (58.3). Valores em `settings`: server_name, server_url, server_port, server_id (uuid estável, nasce na 1ª
leitura) e mdns_enabled."""
import ipaddress
import os
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, render_template, request

import config
from server.auth import admin_required
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


PORT_MIN, PORT_MAX = 1024, 65535


def get_port(conn):
    """60.1: porta salva em Configurações → Servidor (settings.server_port); inválida ou ausente = 32000."""
    try:
        p = int(get_setting(conn, "server_port", "") or 0)
    except ValueError:
        p = 0
    return p if PORT_MIN <= p <= PORT_MAX else config.DEFAULT_PORT


def load_port():
    """60.1: na partida (run.py), banco → config.PORT."""
    with get_db() as conn:
        config.PORT = get_port(conn)


def port_free(port):
    """60.1: a porta pode ser aberta por este servidor? (a porta atual já é nossa, então vale sempre)."""
    if port == config.PORT:
        return True
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def restart_soon(delay=1.5):
    """60.1: reinicia o processo (execv, mesmo PID, o systemd não percebe) para abrir a porta nova; antes encerra o anúncio mDNS
    (os apps não ficam com o endereço velho). Só roda sob run.py (`config.RESTART_ON_PORT`); em testes não faz nada."""
    if not config.RESTART_ON_PORT:
        return

    def go():
        time.sleep(delay)
        try:
            from server import discovery
            discovery._stop()
        except Exception:
            pass
        os.execv(sys.executable, [sys.executable] + sys.argv)
    threading.Thread(target=go, daemon=True, name="port-restart").start()


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
    return {"name": get_server_name(conn), "url": url, "id": get_server_id(conn), "mdns": mdns_enabled(conn),
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
    port = d.get("port", cur["port"])
    if not isinstance(name, str) or len(name.strip()) > NAME_MAX or not isinstance(mdns, bool) or isinstance(port, bool) or not isinstance(port, int):
        return jerr("err.opcao_invalida", 400)
    if not PORT_MIN <= port <= PORT_MAX:
        return jerr("err.porta_fora_faixa", 400, vars={"min": PORT_MIN, "max": PORT_MAX})
    if not port_free(port):
        return jerr("err.porta_em_uso", 400, vars={"port": port})
    url, err = normalize_url(d["url"]) if "url" in d else (cur["url"], None)  # ausente = mantém o atual
    if err:
        return jerr(err, 400)
    with get_db() as conn:
        _upsert(conn, "server_name", name.strip() or NAME_DEFAULT)
        _upsert(conn, "server_url", url)
        _upsert(conn, "mdns_enabled", "1" if mdns else "0")
        _upsert(conn, "server_port", str(port))
        conn.commit()
        out = _payload(conn)
    out["restart"] = port != config.PORT  # 60.1: a porta nova só abre com o processo reiniciado
    if out["restart"]:
        out["new_port"] = port
        restart_soon()
        return jsonify(out)
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
