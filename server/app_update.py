"""63.3: atualização dos apps Android (celular e TV, o mesmo APK).

O `build_apk.sh` publica `apk/starflix.apk` + `apk/version.json`. Estas duas rotas são **públicas** (o APK não tem segredos; o aviso
precisa funcionar antes do login do celular e do pareamento da TV):
  GET /api/app/version -> {available, versionCode, versionName, size, sha256, built_at, url}  (available=false se não há APK)
  GET /api/app/apk     -> o arquivo (Range, ETag = sha256); 404 se não há APK
Compilar uma versão nova vale na hora: o json é relido quando a data do arquivo muda, sem reiniciar o servidor.
"""
import json
import os
import threading

from flask import Blueprint, jsonify, request, send_file

import config
from server.i18n import jerr
from server.tv_auth import rate_ok

bp = Blueprint("app_update", __name__)

_lock = threading.Lock()
_cache = {"key": None, "info": None}


def _paths():
    d = getattr(config, "APK_DIR", os.path.join(config.BASE_DIR, "apk"))
    return os.path.join(d, "version.json"), os.path.join(d, "starflix.apk")


def current():
    """Dados do APK publicado ou None (sem version.json, json inválido, sem APK ou tamanho diferente do declarado)."""
    jp, ap = _paths()
    try:
        js, st = os.stat(jp), os.stat(ap)
    except OSError:
        return None
    key = (js.st_mtime_ns, js.st_size, st.st_mtime_ns, st.st_size)
    with _lock:
        if _cache["key"] == key:
            return _cache["info"]
    info = None
    try:
        with open(jp, encoding="utf-8") as f:
            d = json.load(f)
        code = int(d["versionCode"])
        sha = str(d["sha256"]).lower()
        if code > 0 and len(sha) == 64 and int(d.get("size", st.st_size)) == st.st_size:
            info = {"versionCode": code, "versionName": str(d.get("versionName", "")), "size": st.st_size,
                    "sha256": sha, "built_at": str(d.get("built_at", ""))}
    except (OSError, ValueError, KeyError, TypeError):
        info = None
    with _lock:
        _cache["key"], _cache["info"] = key, info
    return info


@bp.route("/api/app/version")
def version():
    if not rate_ok("app-version", request.remote_addr or "?", 60, 60):
        return jerr("err.muitos_pedidos_tente_novo_instantes", 429)
    info = current()
    r = jsonify(available=False) if not info else jsonify(available=True, url="/api/app/apk", **info)
    r.headers["Cache-Control"] = "no-store"
    return r


@bp.route("/api/app/apk")
def apk():
    if not rate_ok("app-apk", request.remote_addr or "?", 20, 60):
        return jerr("err.muitos_pedidos_tente_novo_instantes", 429)
    info = current()
    if not info:
        return jsonify(available=False), 404
    r = send_file(_paths()[1], mimetype="application/vnd.android.package-archive", conditional=True, etag=False,
                  as_attachment=True, download_name="starflix.apk", max_age=0)
    r.headers["ETag"] = '"%s"' % info["sha256"]
    r.headers["Cache-Control"] = "no-cache"
    return r
