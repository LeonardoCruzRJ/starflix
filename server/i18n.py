"""59.1: catálogos de idiomas (i18n/<idioma>.json), t() com variáveis, plurais CLDR e fallback."""
import hashlib
import json
import os
import re
from datetime import date, datetime

import config
from flask import g, has_request_context, request, session

from server.db import get_db

I18N_DIR = os.path.join(config.BASE_DIR, "i18n")
DEFAULT = "pt-BR"  # idioma-fonte
LANGS = [  # (código, nome no próprio idioma)
    ("pt-BR", "Português (Brasil)"), ("en-US", "English"), ("es-ES", "Español"), ("ru-RU", "Русский"),
    ("fr-FR", "Français"), ("de-DE", "Deutsch"), ("it-IT", "Italiano"), ("ja-JP", "日本語"),
    ("zh-CN", "简体中文"), ("tr-TR", "Türkçe"),
]
CODES = [c for c, _ in LANGS]
CHAIN_TAIL = ["en-US", DEFAULT]  # depois do idioma pedido: inglês, depois a fonte, depois a chave
_BY_LOWER = {c.lower(): c for c in CODES}
_BY_BASE = {}
for _c in CODES:
    _BY_BASE.setdefault(_c.split("-")[0].lower(), _c)

_cache = {}  # código -> (mtime, dict)


def norm(lang):
    """'pt', 'pt_br', 'EN-gb' -> código suportado; None se não houver."""
    if not lang:
        return None
    s = str(lang).strip().replace("_", "-").lower()
    return _BY_LOWER.get(s) or _BY_BASE.get(s.split("-")[0])


def catalog(lang):
    """Dicionário do idioma (vazio se o arquivo não existir). Recarrega se o arquivo mudou."""
    code = norm(lang) or DEFAULT
    path = os.path.join(I18N_DIR, code + ".json")
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    hit = _cache.get(code)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data = {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    _cache[code] = (mtime, data)
    return data


def plural_category(lang, n):
    """Categoria CLDR (one/few/many/other) para o número n."""
    code = norm(lang) or DEFAULT
    base = code.split("-")[0]
    try:
        f = float(n)
    except (TypeError, ValueError):
        return "other"
    is_int = f == int(f)
    i = abs(int(f))
    if base in ("ja", "zh"):
        return "other"
    if base == "ru":
        if not is_int:
            return "other"
        if i % 10 == 1 and i % 100 != 11:
            return "one"
        if 2 <= i % 10 <= 4 and not 12 <= i % 100 <= 14:
            return "few"
        return "many"
    if base in ("pt", "fr"):
        return "one" if i in (0, 1) else "other"
    return "one" if f == 1 else "other"  # en, es, de, it, tr


class _Safe(dict):
    def __missing__(self, k):
        return "{" + k + "}"


_VAR = re.compile(r"\{(\w+)\}")


def _fmt(text, vars):
    if not vars or "{" not in text:
        return text
    return _VAR.sub(lambda m: str(vars[m.group(1)]) if m.group(1) in vars else m.group(0), text)


def _lookup(code, key, n):
    cat = catalog(code)
    if key in cat:
        return cat[key]
    if n is not None:
        cat_pl = plural_category(code, n)
        for suffix in (cat_pl, "other"):
            if key + "." + suffix in cat:
                return cat[key + "." + suffix]
    return None


def has(key, lang=None):
    code = norm(lang) or DEFAULT
    cat = catalog(code)
    return key in cat or any(key + "." + s in cat for s in ("one", "few", "many", "other"))


def t(key, lang=None, **vars):
    """Texto de `key` no idioma (fallback: en-US, pt-BR, a própria chave). Com n=... escolhe o plural."""
    code = norm(lang) or DEFAULT
    n = vars.get("n")
    for c in [code] + [x for x in CHAIN_TAIL if x != code]:
        txt = _lookup(c, key, n)
        if txt is not None:
            return _fmt(txt, vars)
    return _fmt(key, vars)


# ---- 59.2: idioma ativo -----------------------------------------------------------------------------------------------
def pick(profile=None, account=None, cookie=None, accept=(), server=None):
    """Ordem: perfil → conta → cookie `sf_lang` → Accept-Language → padrão do servidor → pt-BR."""
    for c in (profile, account, cookie):
        n = norm(c)
        if n:
            return n
    for a in accept:
        n = norm(a) if a != "*" else None
        if n:
            return n
    return norm(server) or DEFAULT


def _saved_lang(row):
    try:
        d = json.loads(row["prefs"]) if row and row["prefs"] else {}
    except ValueError:
        return None
    return d.get("lang") if isinstance(d, dict) else None


def current_lang():
    """Idioma da requisição (calculado no primeiro uso e guardado em g.lang). Fora de requisição: pt-BR."""
    if not has_request_context():
        return DEFAULT
    lang = g.get("lang")
    if lang:
        return lang
    prof = acct = None
    uid, pid = session.get("user_id"), session.get("profile_id")
    with get_db() as conn:
        if uid:
            if pid:
                prof = _saved_lang(conn.execute("SELECT prefs FROM profiles WHERE id = ? AND user_id = ?", (pid, uid)).fetchone())
            acct = _saved_lang(conn.execute("SELECT prefs FROM users WHERE id = ?", (uid,)).fetchone())
        r = conn.execute("SELECT value FROM settings WHERE key = 'default_lang'").fetchone()
    g.lang = pick(prof, acct, request.cookies.get("sf_lang"), [v for v, _q in request.accept_languages], r["value"] if r else None)
    return g.lang


def tr(key, **vars):
    """t() no idioma da requisição (usado pelo Jinja e pelo servidor)."""
    return t(key, current_lang(), **vars)


# ---- 59.20: formatos pelo idioma ativo (datas, durações, números) -------------------------------------------------------
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def fmt_date(iso, lang=None):
    """'2026-06-04' -> '4 de junho de 2026' (pt-BR) / padrão `fmt.date` do idioma; vazio se a data for inválida."""
    m = _ISO.match(iso or "")
    if not m:
        return ""
    y, mo, d = (int(x) for x in m.groups())
    try:
        date(y, mo, d)
    except ValueError:
        return ""
    lang = lang or current_lang()
    return t("fmt.date", lang, d=d, m=mo, y=y, month=t("fmt.month.%d" % mo, lang))


def fmt_stamp(ts, lang=None):
    """Epoch -> data e hora curtas pelo padrão `fmt.stamp` do idioma (vazio sem data)."""
    if not ts:
        return ""
    x = datetime.fromtimestamp(ts)
    return t("fmt.stamp", lang or current_lang(), d="%02d" % x.day, m="%02d" % x.month, y=x.year, H="%02d" % x.hour, M="%02d" % x.minute)


def fmt_hm(seconds, lang=None):
    """Duração curta (2h 31min / 45min); vazio abaixo de 1 min."""
    m = int((seconds or 0) // 60)
    if m <= 0:
        return ""
    lang = lang or current_lang()
    return t("fmt.dur.short_h_m", lang, h=m // 60, m="%02d" % (m % 60)) if m >= 60 else t("fmt.dur.short_m", lang, m=m)


def fmt_num(n, digits=None, lang=None):
    """Número com separadores do idioma (`fmt.dec_sep`, `fmt.thou_sep`); `digits` fixa as casas decimais."""
    lang = lang or current_lang()
    s = ("{:,.%df}" % digits).format(n) if digits is not None else "{:,}".format(n)
    return s.replace(",", "\0").replace(".", t("fmt.dec_sep", lang)).replace("\0", t("fmt.thou_sep", lang))


# ---- 59.19: mensagens do servidor (código + texto já no idioma ativo) ---------------------------------------------------
class Msg(str):
    """Texto no idioma ativo que também leva a chave (`key`) e as variáveis (`vars`); serve como str comum."""
    key = None
    vars = None


def E(key, **vars):
    """Mensagem de `key` no idioma da requisição; passe para jerr() ou devolva de validadores no lugar de um texto fixo."""
    m = Msg(tr(key, **vars))
    m.key, m.vars = key, vars or None
    return m


def jerr(msg, status=400, vars=None, **extra):
    """Resposta JSON de erro: {code, message, error (= message, compatível), vars?, **extra}, status.
    `msg`: chave do catálogo, Msg/E(), exceção que carrega uma Msg ou texto livre (sem `code`)."""
    from flask import jsonify
    if isinstance(msg, BaseException):
        msg = msg.args[0] if msg.args and isinstance(msg.args[0], str) else str(msg)
    if not isinstance(msg, Msg):
        msg = E(msg, **(vars or {})) if isinstance(msg, str) and has(msg) else Msg(str(msg))
    body = {"message": str(msg), "error": str(msg)}
    if msg.key:
        body["code"] = msg.key
        if msg.vars:
            body["vars"] = msg.vars
    body.update(extra)
    return jsonify(body), status


# ---- 59.3: pacote do idioma para o site (catálogo já com fallback) -----------------------------------------------------
_bundles = {}  # código -> (assinatura dos mtimes, etag, corpo JSON em bytes)


def bundle(lang):
    """(etag, corpo JSON) com todas as chaves do idioma, já completadas por en-US e pt-BR. None se o idioma não existe."""
    if lang not in CODES:
        return None
    order = [DEFAULT]  # do menos para o mais prioritário: pt-BR < en-US < idioma
    if lang != DEFAULT:
        order += [c for c in ("en-US", lang) if c not in order]
    sig = tuple(os.path.getmtime(os.path.join(I18N_DIR, c + ".json")) if os.path.exists(os.path.join(I18N_DIR, c + ".json")) else 0 for c in order)
    hit = _bundles.get(lang)
    if hit and hit[0] == sig:
        return hit[1], hit[2]
    strings = {}
    for c in order:  # fonte primeiro; cada idioma por cima do anterior
        strings.update(catalog(c))
    body = json.dumps({"lang": lang, "strings": strings}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    etag = hashlib.sha1(body).hexdigest()[:16]
    _bundles[lang] = (sig, etag, body)
    return etag, body
