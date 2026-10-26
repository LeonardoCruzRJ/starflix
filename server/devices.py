"""52.6: aparelhos que já tocaram (`client_caps`) e o cartão "Aparelhos" do Painel: lista, caps resumido, marcar «precisa tocar sem transcode» e apagar."""
import hashlib
import time

from flask import Blueprint, g, jsonify, request, session

from server.auth import admin_required
from server.caps import Caps
from server.db import get_db
from server.i18n import jerr

bp = Blueprint("devices", __name__)

SEEN_EVERY = 3600  # s: o mesmo aparelho com o mesmo `caps` é regravado no máximo 1×/hora
_V = {"h264": "H.264", "hevc": "HEVC", "av1": "AV1", "vp9": "VP9", "vp8": "VP8"}
_A = {"aac": "AAC", "mp3": "MP3", "opus": "Opus", "vorbis": "Vorbis", "flac": "FLAC", "ac3": "AC3", "eac3": "EAC3"}


def _label(ua):
    ua = ua or ""
    if "Dalvik" in ua or "okhttp" in ua or "ExoPlayer" in ua or "Media3" in ua:
        return "App Android"
    so = next((n for k, n in (("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"), ("Windows", "Windows"), ("Mac OS X", "Mac"), ("Linux", "Linux")) if k in ua), "")
    nav = next((n for k, n in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"), ("Safari/", "Safari")) if k in ua), "Navegador")
    return f"{nav} ({so})" if so else nav


def device_key():
    """(chave, rótulo) do aparelho do pedido: TV pelo `tv_devices.id`; o resto por usuário + agente."""
    did = g.get("tv_device")
    if did:
        with get_db() as conn:
            r = conn.execute("SELECT name FROM tv_devices WHERE id = ?", (did,)).fetchone()
        return f"tv:{did}", (r["name"] if r and r["name"] else "TV")
    ua = request.headers.get("User-Agent", "")[:300]
    return f"web:{session['user_id']}:{hashlib.sha1(ua.encode()).hexdigest()[:10]}", _label(ua)


def touch(caps):
    """UPSERT do aparelho em `/play`; nunca derruba a reprodução."""
    if not isinstance(caps, Caps):
        return
    try:
        key, label = device_key()
        now, q = int(time.time()), caps.query()
        with get_db() as conn:
            r = conn.execute("SELECT caps, last_seen FROM client_caps WHERE client_key = ?", (key,)).fetchone()
            if r and r["caps"] == q and now - (r["last_seen"] or 0) < SEEN_EVERY:
                return
            conn.execute(
                "INSERT INTO client_caps (client_key, user_id, label, caps, required, last_seen) VALUES (?, ?, ?, ?, 0, ?) "
                "ON CONFLICT(client_key) DO UPDATE SET user_id = excluded.user_id, label = excluded.label, caps = excluded.caps, last_seen = excluded.last_seen",
                (key, session["user_id"], label, q, now))
            conn.commit()
    except Exception as e:  # noqa: BLE001
        print(f"[devices] não gravou o aparelho: {e}", flush=True)


def summary(q):
    """Resumo do `caps` guardado: `H.264, HEVC · AAC, AC3 · 10 bits · HDR · 6 canais`."""
    kv = dict(p.partition("=")[::2] for p in (q or "").split("&"))
    names = lambda k, m: ", ".join(m[x] for x in kv.get(k, "").split(".") if x in m) or "—"
    parts = [names("v", _V), names("a", _A)]
    if kv.get("b10") == "1":
        parts.append("10 bits")
    if kv.get("hdr") == "1":
        parts.append("HDR")
    parts.append(f"{kv.get('ch', '2')} canais")
    return " · ".join(parts)


def _rows(conn):
    return [{"key": r["client_key"], "label": r["label"], "user": r["username"] or "—", "summary": summary(r["caps"]), "required": bool(r["required"]), "seen": r["last_seen"]}
            for r in conn.execute("SELECT c.client_key, c.label, c.caps, c.required, c.last_seen, u.username FROM client_caps c LEFT JOIN users u ON u.id = c.user_id "
                                  "ORDER BY c.last_seen DESC, c.client_key")]


@bp.route("/admin/devices/data")
@admin_required
def data():
    with get_db() as conn:
        return jsonify(devices=_rows(conn))


@bp.route("/admin/devices/required", methods=["POST"])
@admin_required
def required():
    d = request.get_json(silent=True)
    if not isinstance(d, dict) or not isinstance(d.get("key"), str) or not isinstance(d.get("required"), bool):
        return jerr("err.dados_invalidos", 400)
    with get_db() as conn:
        n = conn.execute("UPDATE client_caps SET required = ? WHERE client_key = ?", (int(d["required"]), d["key"])).rowcount
        conn.commit()
        return (jsonify(devices=_rows(conn)), 200) if n else jerr("err.aparelho_nao_encontrado", 404)


@bp.route("/admin/devices/delete", methods=["POST"])
@admin_required
def delete():
    d = request.get_json(silent=True)
    if not isinstance(d, dict) or not isinstance(d.get("key"), str):
        return jerr("err.dados_invalidos", 400)
    with get_db() as conn:
        n = conn.execute("DELETE FROM client_caps WHERE client_key = ?", (d["key"],)).rowcount
        conn.commit()
        return (jsonify(devices=_rows(conn)), 200) if n else jerr("err.aparelho_nao_encontrado", 404)
