"""59.3: API de idiomas. GET /api/i18n/<idioma> (catálogo completo, ETag, pública) e POST /api/i18n/set (cookie `sf_lang` +
preferência do perfil, ou da conta se ainda não há perfil escolhido; sem login só o cookie).
59.37: com login, também ajusta o idioma dos agentes e refaz os metadados de todas as bibliotecas (server/meta_lang.py)."""
import hashlib
import json
import logging

from flask import Blueprint, Response, jsonify, request, session

from server import i18n, meta_lang
from server.i18n import jerr
from server.db import get_db

bp = Blueprint("i18n_api", __name__)

COOKIE_MAX_AGE = 365 * 24 * 3600


@bp.route("/api/i18n/<lang>")
def catalog(lang):
    b = i18n.bundle(lang)
    if not b:
        return jerr("err.idioma_nao_suportado", 404)
    etag, body = b
    pre = request.args.get("prefix", "")[:32]
    if pre:  # 62.9: só as chaves com o prefixo (a Roku não precisa das 1500 do site)
        sub = {k: v for k, v in json.loads(body)["strings"].items() if k.startswith(pre)}
        body = json.dumps({"lang": lang, "strings": sub}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        etag = hashlib.sha1(body).hexdigest()[:16]
    r = Response(body, mimetype="application/json")
    r.set_etag(etag)
    r.headers["Cache-Control"] = "public, no-cache"  # sempre revalida (304 barato): a troca de idioma nunca mostra catálogo velho
    return r.make_conditional(request)


def _parse(row):
    try:
        d = json.loads(row["prefs"]) if row and row["prefs"] else None
    except ValueError:
        d = None
    return d if isinstance(d, dict) else None


def _save(lang):
    uid, pid = session.get("user_id"), session.get("profile_id")
    if not uid:
        return
    with get_db() as conn:
        if pid:
            row = conn.execute("SELECT prefs FROM profiles WHERE id = ? AND user_id = ?", (pid, uid)).fetchone()
            if not row:
                return
            d = _parse(row)
            if d is None:  # perfil sem preferências próprias herda as da conta (como user_prefs): copia antes de gravar o idioma
                d = _parse(conn.execute("SELECT prefs FROM users WHERE id = ?", (uid,)).fetchone()) or {}
            d["lang"] = lang
            conn.execute("UPDATE profiles SET prefs = ? WHERE id = ? AND user_id = ?", (json.dumps(d), pid, uid))
        else:
            d = _parse(conn.execute("SELECT prefs FROM users WHERE id = ?", (uid,)).fetchone()) or {}
            d["lang"] = lang
            conn.execute("UPDATE users SET prefs = ? WHERE id = ?", (json.dumps(d), uid))
        conn.commit()


@bp.route("/api/i18n/set", methods=["POST"])
def set_lang():
    d = request.get_json(silent=True)
    lang = d.get("lang") if isinstance(d, dict) else None
    if not isinstance(lang, str) or lang not in i18n.CODES:
        return jerr("err.idioma_nao_suportado", 400)
    _save(lang)
    meta = False
    if session.get("user_id"):  # 59.37: os agentes seguem o idioma do usuário; a troca refaz os metadados de todas as bibliotecas
        try:
            meta = meta_lang.follow(lang)
        except Exception:
            logging.exception("falha ao aplicar o idioma %s nos agentes", lang)
    r = jsonify(ok=True, lang=lang, metadata_refresh=meta)
    r.set_cookie("sf_lang", lang, max_age=COOKIE_MAX_AGE, samesite="Lax", httponly=True)
    return r
