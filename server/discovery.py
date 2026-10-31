"""58.3: anúncio do servidor na rede local por mDNS/DNS-SD (`_starflix._tcp.local.`) para os apps (NsdManager) o acharem sem
digitar endereço. TXT: id, name, v, path=/api/server-info. Tudo **falha em silêncio** (só log): sem a lib `zeroconf`, sem
multicast ou com o interruptor desligado em /admin/server o servidor sobe normalmente. Reavalia a cada 5 min (IP novo por DHCP,
interruptor ligado/desligado) e na hora ao salvar /admin/server."""
import json
import logging
import socket
import threading
import time
from urllib.parse import urlsplit

import config
from server.admin_server import get_server_id, get_server_name, local_addresses, mdns_enabled
from server.db import get_db

SERVICE_TYPE = "_starflix._tcp.local."
RESCAN = 300
log = logging.getLogger("starflix.mdns")
_lock = threading.Lock()
_state = {"zc": None, "info": None, "ips": [], "warned": ""}


def _warn(msg):
    if _state["warned"] != msg:  # repetição a cada reavaliação não polui o log
        _state["warned"] = msg
        log.warning(msg)


def _ips():
    return sorted(urlsplit(u).hostname for u in local_addresses())


def _start():
    with _lock:
        if _state["zc"]:
            return
        with get_db() as conn:
            if not mdns_enabled(conn):
                return
            sid, name = get_server_id(conn), get_server_name(conn)
        ips = _ips()
        if not ips:
            _warn("mDNS: nenhum endereço de rede local para anunciar")
            return
        try:
            from zeroconf import IPVersion, ServiceInfo, Zeroconf
        except ImportError:
            _warn("mDNS desligado: falta a dependência `zeroconf` (python3 -m pip install -r requirements.txt)")
            return
        zc = None
        try:
            info = ServiceInfo(SERVICE_TYPE, f"StarFlix-{sid[:8]}.{SERVICE_TYPE}", port=config.PORT,
                               addresses=[socket.inet_aton(i) for i in ips], server=f"starflix-{sid[:8]}.local.",
                               properties={"id": sid, "name": name, "v": config.VERSION, "path": "/api/server-info"})
            zc = Zeroconf(ip_version=IPVersion.V4Only)
            zc.register_service(info, allow_name_change=True)
        except Exception as e:  # rede sem multicast, porta 5353 ocupada, interface sem suporte…
            _warn(f"mDNS indisponível: {e}")
            if zc:
                try:
                    zc.close()
                except Exception:
                    pass
            return
        _state.update(zc=zc, info=info, ips=ips, warned="")
        log.info("mDNS: anunciando %s em %s:%s", SERVICE_TYPE, ", ".join(ips), config.PORT)


def _stop():
    with _lock:
        zc, info = _state["zc"], _state["info"]
        _state.update(zc=None, info=None, ips=[])
        if zc:
            try:
                zc.unregister_service(info)
                zc.close()
            except Exception:
                pass
            log.info("mDNS: anúncio encerrado")


def _loop():
    while True:
        time.sleep(RESCAN)
        try:
            with get_db() as conn:
                on = mdns_enabled(conn)
            if not on and _state["zc"]:
                _stop()
            elif on and (not _state["zc"] or _state["ips"] != _ips()):
                _stop()
                _start()
        except Exception:
            log.exception("mDNS: erro ao reavaliar")


def _boot():
    try:
        _start()
    except Exception:
        log.exception("mDNS: erro ao iniciar")
    _loop()


MAGIC = b"STARFLIX_DISCOVER"
_udp_seen = {}  # ip -> instante do último pedido (limite simples contra enxurrada)


def discover_reply(data, ip="?", now=None):
    """62.2: resposta ao broadcast UDP (bytes JSON) ou None. Vale o mesmo interruptor do mDNS; só devolve o que /api/server-info já é público
    (app, id, name, version, port). Quem chama responde para o IP de origem; o app monta o endereço com esse IP e `port`."""
    if (data or b"").strip() != MAGIC:
        return None
    now = time.time() if now is None else now
    if now - _udp_seen.get(ip, 0) < 0.3:
        return None
    if len(_udp_seen) > 500:
        _udp_seen.clear()
    _udp_seen[ip] = now
    with get_db() as conn:
        if not mdns_enabled(conn):
            return None
        sid, name = get_server_id(conn), get_server_name(conn)
    return json.dumps({"app": "starflix", "id": sid, "name": name, "version": config.VERSION, "port": config.PORT}).encode("utf-8")


def _udp_loop():
    """62.2: escuta UDP em config.DISCOVERY_PORT. Falha em silêncio (porta ocupada etc.) e tenta de novo a cada 5 min."""
    while True:
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", config.DISCOVERY_PORT))
            log.info("Descoberta UDP: escutando na porta %s", config.DISCOVERY_PORT)
            while True:
                data, addr = sock.recvfrom(256)
                try:
                    out = discover_reply(data, addr[0])
                    if out:
                        sock.sendto(out, addr)
                except Exception:
                    log.exception("Descoberta UDP: erro ao responder")
        except OSError as e:
            _warn(f"Descoberta UDP indisponível: {e}")
        finally:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
        time.sleep(RESCAN)


def start():
    """Chamada uma vez na subida (run.py): thread de fundo, não atrasa nem derruba o servidor."""
    threading.Thread(target=_boot, daemon=True, name="mdns").start()
    threading.Thread(target=_udp_loop, daemon=True, name="udp-discovery").start()  # 62.2


def refresh_async():
    """Chamada ao salvar /admin/server (nome ou interruptor mudou): reanuncia sem travar a resposta."""
    def go():
        try:
            _stop()
            _start()
        except Exception:
            log.exception("mDNS: erro ao reanunciar")
    threading.Thread(target=go, daemon=True, name="mdns-refresh").start()
