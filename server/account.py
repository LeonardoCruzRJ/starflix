"""Conta do usuário (Fase 26): foto de perfil (26.2)."""
import json
import os
import re
import secrets
from urllib.parse import urlparse
from xml.sax.saxutils import escape

from werkzeug.security import check_password_hash, generate_password_hash
from flask import Blueprint, Response, abort, jsonify, render_template, request, send_from_directory, session

import config
from server.admin_edit import MAX_IMG, _sniff
from server.auth import _blocked, _fail, _FAILS, login_required
from server import i18n
from server.i18n import jerr
from server.db import get_db

bp = Blueprint("account", __name__)


LANGS = [("", "Padrão do item"), ("pt", "Português"), ("en", "Inglês"), ("es", "Espanhol"), ("fr", "Francês"), ("de", "Alemão"),  # i18n-ok: fonte pt-BR; o texto exibido vem de opt_label()
         ("it", "Italiano"), ("ja", "Japonês"), ("ko", "Coreano"), ("zh", "Chinês"), ("ru", "Russo")]  # i18n-ok: fonte pt-BR; o texto exibido vem de opt_label()
SETTINGS = {  # chave -> (padrão, opções [(valor, rótulo)])  # i18n-ok: fonte pt-BR; o texto exibido vem de opt_label()
    "lang": (i18n.DEFAULT, list(i18n.LANGS)),  # 59.3: os 10 idiomas do StarFlix
    "audio_lang": ("", LANGS),
    "sub_lang": ("", LANGS),
    "sub_mode": ("", [("", "Selecionado manualmente"), ("off", "Desligadas"), ("forced", "Somente forçadas"), ("foreign", "Com áudio estrangeiro")]),  # i18n-ok: fonte pt-BR; o texto exibido vem de opt_label()
    "sdh": ("standard", [("standard", "Preferir legendas padrão"), ("sdh", "Preferir legendas para deficientes auditivos (SDH)")]),  # i18n-ok: fonte pt-BR; o texto exibido vem de opt_label()
    "forced": ("nonforced", [("nonforced", "Preferir legendas não forçadas"), ("forced", "Preferir legendas forçadas")]),  # i18n-ok: fonte pt-BR; o texto exibido vem de opt_label()
    "seen": ("all", [("all", "Filmes & Séries"), ("movies", "Filmes"), ("shows", "Séries"), ("none", "Nenhum")]),  # i18n-ok: fonte pt-BR; o texto exibido vem de opt_label()
    "reviews": ("all", [("all", "Todas as análises"), ("none", "Ninguém")]),  # i18n-ok: fonte pt-BR; o texto exibido vem de opt_label()
    "auto_next": ("on", [("on", "Sim, com contagem regressiva"), ("off", "Não, só mostrar o botão")]),  # 48.4: próximo episódio nos créditos  # i18n-ok: fonte pt-BR; o texto exibido vem de opt_label()
    "skip_intro": ("ask", [("ask", "Perguntar"), ("always", "Pular sempre"), ("never", "Nunca")]),  # 48.2: abertura no player
    # 47.2: estilo da legenda do player (padrões = aparência anterior)  # i18n-ok: fonte pt-BR; o texto exibido vem de opt_label()
    "sub_size": ("m", [("p", "Pequeno"), ("m", "Médio"), ("g", "Grande"), ("gg", "Muito grande")]),  # i18n-ok: fonte pt-BR; o texto exibido vem de opt_label()
    "sub_color": ("white", [("white", "Branco"), ("yellow", "Amarelo"), ("cyan", "Ciano"), ("green", "Verde")]),
    "sub_bg": ("shadow", [("none", "Nenhum"), ("shadow", "Sombra"), ("box", "Caixa translúcida")]),  # i18n-ok: fonte pt-BR; o texto exibido vem de opt_label()
    "sub_pos": ("mid", [("low", "Baixa"), ("mid", "Média"), ("high", "Alta")]),  # i18n-ok: fonte pt-BR; o texto exibido vem de opt_label()
}


def user_prefs(uid=None):
    """Preferências da conta (users.prefs) com padrões; sempre devolve todas as chaves."""
    uid = uid or session.get("user_id")
    pid = session.get("profile_id") if uid == session.get("user_id") else None
    with get_db() as conn:
        r = conn.execute("SELECT prefs FROM profiles WHERE id = ? AND user_id = ? AND prefs IS NOT NULL", (pid, uid)).fetchone() if pid else None
        if not r:  # perfil sem preferências próprias: parte das da conta
            r = conn.execute("SELECT prefs FROM users WHERE id = ?", (uid,)).fetchone()
    try:
        saved = json.loads(r["prefs"]) if r and r["prefs"] else {}
    except ValueError:
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    out = {k: (saved.get(k) if saved.get(k) in [v for v, _ in opts] else d) for k, (d, opts) in SETTINGS.items()}
    out["auto"] = 0 if saved.get("auto") in (0, False) else 1
    if uid == session.get("user_id"):
        out["lang"] = i18n.current_lang()  # 59.4: mostra o idioma em uso (escolhido ou automático), não o padrão
    return out


def opt_label(key, val):
    """59.15: rótulo da opção no idioma ativo (os textos de SETTINGS são só a fonte em pt-BR)."""
    if key == "lang":
        return dict(SETTINGS["lang"][1]).get(val, val)  # nomes dos idiomas ficam no próprio idioma
    if key in ("audio_lang", "sub_lang"):
        k = "lang." + val if val else "set.lang_item"
    elif key == "sub_mode":
        k = "set.sub_mode." + (val or "manual")
    elif key in ("sub_size", "sub_color", "sub_bg", "sub_pos"):
        k = f"player.sty.{key}.{val}"
    else:
        k = f"set.{key}.{val}"
    return i18n.tr(k) if i18n.has(k) else dict(SETTINGS[key][1]).get(val, val)


def _label(key, val):
    if key in ("audio_lang", "sub_lang") and not val:
        return i18n.tr("set.default")
    return opt_label(key, val)


def _remove_avatar_file(name):
    if name:
        try:
            os.remove(os.path.join(config.AVATARS_DIR, os.path.basename(name)))
        except OSError:
            pass


def avatar_url(user_id, name):
    """URL da foto do usuário (o nome do arquivo muda a cada upload e força o cache a renovar); None sem foto."""
    return f"/avatar/{user_id}?v={name}" if name else None


def profile_photo_url(pid, name):
    """URL da foto do perfil (o nome do arquivo muda a cada upload); None sem foto."""
    return f"/pavatar/{pid}?v={name}" if name else None


def _pphoto():
    """Foto (ou avatar com a inicial) do perfil em uso."""
    pid = session.get("profile_id")
    with get_db() as conn:
        p = conn.execute("SELECT photo FROM profiles WHERE id = ?", (pid,)).fetchone()
    return profile_photo_url(pid, p["photo"] if p else None) or f"/pavatar/{pid}"


@bp.route("/pavatar/<int:pid>")
@login_required
def pavatar(pid):
    """Foto do perfil (só de perfis do próprio usuário); sem foto devolve um SVG com a inicial na cor do perfil."""
    with get_db() as conn:
        p = conn.execute("SELECT name, avatar, photo FROM profiles WHERE id = ? AND user_id = ?", (pid, session["user_id"])).fetchone()
    if not p:
        abort(404)
    name = os.path.basename(p["photo"] or "")
    if name and os.path.isfile(os.path.join(config.AVATARS_DIR, name)):
        resp = send_from_directory(config.AVATARS_DIR, name, conditional=True, max_age=86400)
        resp.headers["Cache-Control"] = "private, max-age=86400"
        return resp
    color = p["avatar"] if re.fullmatch(r"#[0-9a-fA-F]{6}", p["avatar"] or "") else "#e5a00d"
    letter = escape(((p["name"] or "?").strip() or "?")[0].upper())
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">' f'<rect width="100" height="100" fill="{color}"/>'
           f'<text x="50" y="50" dy=".35em" text-anchor="middle" font-family="sans-serif" font-size="52" fill="#ffffff">{letter}</text></svg>')
    return Response(svg, mimetype="image/svg+xml", headers={"Cache-Control": "private, max-age=0, must-revalidate"})


@bp.route("/account/avatar", methods=["POST"])
@login_required
def avatar_set():
    f = request.files.get("file")
    if not f:
        return jerr("err.escolha_foto", 400)
    data = f.read(MAX_IMG + 1)
    if len(data) > MAX_IMG:
        return jerr("err.imagem_maior_que_10_mb", 400)
    ext = _sniff(data)
    if not ext:
        return jerr("err.use_jpg_png_ou_webp", 400)
    uid, pid = session["user_id"], session["profile_id"]  # a foto é do perfil em uso, não da conta
    name = f"p{pid}-{secrets.token_hex(4)}{ext}"
    os.makedirs(config.AVATARS_DIR, exist_ok=True)
    with open(os.path.join(config.AVATARS_DIR, name), "wb") as fh:
        fh.write(data)
    with get_db() as conn:
        old = conn.execute("SELECT photo FROM profiles WHERE id = ? AND user_id = ?", (pid, uid)).fetchone()
        if not old:
            _remove_avatar_file(name)
            abort(404)
        conn.execute("UPDATE profiles SET photo = ? WHERE id = ?", (name, pid))
    _remove_avatar_file(old["photo"])
    return jsonify(ok=True, url=profile_photo_url(pid, name))


@bp.route("/account/avatar", methods=["DELETE"])
@login_required
def avatar_clear():
    uid, pid = session["user_id"], session["profile_id"]
    with get_db() as conn:
        old = conn.execute("SELECT photo FROM profiles WHERE id = ? AND user_id = ?", (pid, uid)).fetchone()
        if not old:
            abort(404)
        conn.execute("UPDATE profiles SET photo = NULL WHERE id = ?", (pid,))
    _remove_avatar_file(old["photo"])
    return jsonify(ok=True)


@bp.route("/avatar/<int:uid>")
@login_required
def avatar(uid):
    """Foto do usuário; sem foto devolve um SVG com a inicial (sempre dá para usar em <img>)."""
    with get_db() as conn:
        u = conn.execute("SELECT username, full_name, avatar FROM users WHERE id = ?", (uid,)).fetchone()
    if not u:
        abort(404)
    name = os.path.basename(u["avatar"] or "")
    if name and os.path.isfile(os.path.join(config.AVATARS_DIR, name)):
        resp = send_from_directory(config.AVATARS_DIR, name, conditional=True, max_age=86400)
        resp.headers["Cache-Control"] = "private, max-age=86400"
        return resp
    letter = escape(((u["full_name"] or u["username"] or "?").strip() or "?")[0].upper())
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" fill="#e5a00d"/>'
           f'<text x="50" y="50" dy=".35em" text-anchor="middle" font-family="sans-serif" font-size="52" fill="#1f1f1f">{letter}</text></svg>')
    return Response(svg, mimetype="image/svg+xml", headers={"Cache-Control": "private, max-age=0, must-revalidate"})


def _me(conn):
    return conn.execute("SELECT id, username, full_name, avatar, created_at, show_badge FROM users WHERE id = ?",
                        (session["user_id"],)).fetchone()


@bp.route("/profile")
@login_required
def profile():
    uid = session["user_id"]
    with get_db() as conn:
        u = _me(conn)
        if not u:
            abort(404)
        pid = session["profile_id"]
        q = lambda sql: conn.execute(sql, (pid,)).fetchone()[0]
        prof = "(SELECT id FROM profiles WHERE id = ?)"
        pr = conn.execute("SELECT name, photo FROM profiles WHERE id = ?", (pid,)).fetchone()
        movies = q(f"SELECT COUNT(DISTINCT item_id) FROM progress WHERE watched = 1 AND item_type = 'movie' AND profile_id IN {prof}")
        eps = q(f"SELECT COUNT(DISTINCT item_id) FROM progress WHERE watched = 1 AND item_type = 'episode' AND profile_id IN {prof}")
        shows = q("SELECT COUNT(DISTINCT e.media_id) FROM progress p JOIN episodes e ON e.id = p.item_id "
                  f"WHERE p.watched = 1 AND p.item_type = 'episode' AND p.profile_id IN {prof}")
        starred = q(f"SELECT COUNT(*) FROM stars WHERE stars > 0 AND profile_id IN {prof}")
        listed = q(f"SELECT COUNT(*) FROM my_list WHERE profile_id IN {prof}")
    name = (pr["name"] if pr else "").strip()
    start = []
    if not (name and pr and pr["photo"]):
        start.append("fill")
    if not starred:
        start.append("rate")
    if not listed:
        start.append("list")
    return render_template("profile.html", u=u, display=name or u["username"], year=(u["created_at"] or "")[:4],
                           movies=movies, shows=shows, eps=eps, start=start, photo=_pphoto(), cont=_profile_continue(uid, pid))


def _profile_continue(user_id, profile_id, limit=3):
    """Celular: os 3 últimos itens de "Continuar Assistindo" do perfil (capa, link e % assistido, igual à fileira do Início)."""
    from server.progress import continue_watching
    with get_db() as conn:
        video_libs = {r["id"] for r in conn.execute("SELECT id FROM libraries WHERE type = 'video'")}
    out = []
    for i in continue_watching(user_id, profile_id, limit=limit, home=True):
        pct = min(100, int(i["position"] / i["duration"] * 100)) if i.get("duration") else 0
        if i["kind"] == "episode":
            title, href, img = i["show"], f"/show/{i['media_id']}", f"/poster/{i['media_id']}"
        elif i.get("lib") in video_libs:  # biblioteca de vídeos não tem capa: usa a miniatura
            title, href, img = i["title"], f"/watch/movie/{i['media_id']}", f"/thumb/{i['media_id']}"
        else:
            title, href, img = i["title"], f"/movie/{i['media_id']}", f"/poster/{i['media_id']}"
        out.append({"title": title, "href": href, "img": img, "pct": pct})
    return out


_LIMITS = {"full_name": 60, "location": 60, "bio": 500, "link": 200}


@bp.route("/profile/edit")
@login_required
def profile_edit():
    with get_db() as conn:
        p = conn.execute("SELECT id, name, photo FROM profiles WHERE id = ? AND user_id = ?", (session["profile_id"], session["user_id"])).fetchone()
    return render_profile_edit(p, pm=False)


def render_profile_edit(p, pm=True):
    """Editar perfil. pm=True (aberto pela lista de perfis, 54.23): só foto, nome e excluir do perfil `p`; pm=False: tela completa do perfil em uso."""
    uid = session["user_id"]
    with get_db() as conn:
        u = conn.execute("SELECT username, full_name, avatar, location, bio, link, show_badge, is_admin FROM users WHERE id = ?", (uid,)).fetchone()
        n = conn.execute("SELECT COUNT(*) FROM profiles WHERE user_id = ?", (uid,)).fetchone()[0]
    if not u or not p:
        abort(404)
    lang = user_prefs()["lang"] if session.get("profile_id") else "pt-BR"
    return render_template("profile_edit.html", u=u, display=(p["name"] or "").strip() or u["username"], pm=pm, pid=p["id"], pname=p["name"] or "",
                           can_delete=pm and n > 1 and not u["is_admin"], photo=profile_photo_url(p["id"], p["photo"]) or f"/pavatar/{p['id']}",
                           lang=lang, lang_opts=SETTINGS["lang"][1], lang_txt=dict(SETTINGS["lang"][1]).get(lang, lang))


@bp.route("/account/profile", methods=["POST"])
@login_required
def profile_save():
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return jerr("err.dados_invalidos", 400)
    field, val = d.get("field"), d.get("value")
    if field == "show_badge":
        val = 1 if val in (True, 1, "1") else 0
    elif field == "username":
        val = val.strip() if isinstance(val, str) else ""
        if not val or len(val) > 40 or any(c.isspace() for c in val):
            return jerr("err.use_1_40_caracteres_sem", 400)
        with get_db() as conn:
            if conn.execute("SELECT 1 FROM users WHERE casefold(username) = casefold(?) AND id != ?",
                            (val, session["user_id"])).fetchone():
                return jerr("err.usuario_ja_existe", 400)
    elif field in _LIMITS:
        if not isinstance(val, str):
            return jerr("err.valor_invalido", 400)
        val = " ".join(val.split()) if field != "bio" else val.strip()
        if len(val) > _LIMITS[field]:
            return jerr("err.maximo_caracteres", 400, vars={"n": _LIMITS[field]})
        if field == "link" and val:
            if not val.lower().startswith(("http://", "https://")):
                if "://" in val:
                    return jerr("err.use_endereco_http_ou_https", 400)
                val = "https://" + val
            pu = urlparse(val)
            try:
                ok = pu.scheme in ("http", "https") and bool(pu.hostname) and (pu.port or 80) > 0 and not any(c.isspace() for c in val)
            except ValueError:
                ok = False
            if not ok:
                return jerr("err.use_endereco_http_ou_https", 400)
        val = val or None
    else:
        return jerr("err.campo_invalido", 400)
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE id = ?", (session["user_id"],)).fetchone():
            abort(404)
        conn.execute(f"UPDATE users SET {field} = ? WHERE id = ?", (val, session["user_id"]))
    return jsonify(ok=True, value=val)


@bp.route("/account/password", methods=["POST"])
@login_required
def password_set():
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return jerr("err.dados_invalidos", 400)
    new, conf, cur = d.get("new"), d.get("confirm"), d.get("current")
    if not all(isinstance(x, str) for x in (new, conf, cur)):
        return jerr("err.dados_invalidos", 400)
    ip = request.remote_addr
    if _blocked(ip):
        return jerr("err.muitas_tentativas_aguarde_alguns_minutos", 429)
    if len(new) < 4:
        return jerr("err.nova_senha_precisa_ter_minimo", 400)
    if new != conf:
        return jerr("err.confirmacao_nao_confere_nova_senha", 400)
    with get_db() as conn:
        u = conn.execute("SELECT password_hash, session_ver FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        if not u:
            abort(404)
        if not check_password_hash(u["password_hash"], cur):
            _fail(ip)
            return jerr("err.senha_atual_incorreta", 400)
        ver = (u["session_ver"] or 0) + (1 if d.get("logout_others") else 0)
        conn.execute("UPDATE users SET password_hash = ?, session_ver = ? WHERE id = ?",
                     (generate_password_hash(new), ver, session["user_id"]))
    _FAILS.pop(ip, None)
    session["sv"] = ver
    return jsonify(ok=True)


@bp.route("/account/settings", methods=["POST"])
@login_required
def settings_save():
    d = request.get_json(silent=True)
    vals = d.get("values") if isinstance(d, dict) else None
    if not isinstance(vals, dict) or not vals:
        return jerr("err.dados_invalidos", 400)
    cur = user_prefs()
    for k, v in vals.items():
        if k == "auto":
            cur["auto"] = 1 if v in (True, 1, "1") else 0
        elif k in SETTINGS and isinstance(v, str) and v in [o for o, _ in SETTINGS[k][1]]:
            cur[k] = v
        else:
            return jerr("err.valor_invalido", 400)
    with get_db() as conn:
        had = conn.execute("SELECT prefs FROM profiles WHERE id = ? AND user_id = ?", (session["profile_id"], session["user_id"])).fetchone()
        try:
            had_lang = bool(json.loads(had["prefs"]).get("lang")) if had and had["prefs"] else False
        except (ValueError, AttributeError):
            had_lang = False
        if "lang" not in vals and not had_lang:  # 59.3: o padrão não vira escolha (senão trava o perfil em pt-BR e ignora o idioma do navegador)
            cur.pop("lang", None)
        conn.execute("UPDATE profiles SET prefs = ? WHERE id = ? AND user_id = ?", (json.dumps(cur), session["profile_id"], session["user_id"]))
    return jsonify(ok=True)


@bp.route("/account")
@login_required
def account():
    uid = session["user_id"]
    with get_db() as conn:
        u = conn.execute("SELECT username, full_name, avatar FROM users WHERE id = ?", (uid,)).fetchone()
    if not u:
        abort(404)
    pf = user_prefs()
    audio_txt = (i18n.tr("acc.sum.track", a=_label("audio_lang", pf["audio_lang"]), s=_label("sub_lang", pf["sub_lang"]), m=_label("sub_mode", pf["sub_mode"]))
                 if pf["auto"] else i18n.tr("acc.sum.auto_off"))
    sub_txt = i18n.tr("acc.sum.sub", a=_label("sub_size", pf["sub_size"]), b=_label("sub_color", pf["sub_color"]), c=_label("sub_bg", pf["sub_bg"]), d=_label("sub_pos", pf["sub_pos"]))
    skip_txt = i18n.tr("acc.sum.skip", a=_label("skip_intro", pf["skip_intro"]), b=_label("auto_next", pf["auto_next"]))
    search_txt = i18n.tr("acc.sum.search", a=_label("sdh", pf["sdh"]), b=_label("forced", pf["forced"]))
    return render_template("account.html", pf=pf, st=SETTINGS, ol=opt_label, audio_txt=audio_txt, search_txt=search_txt, sub_txt=sub_txt, skip_txt=skip_txt, u=u, display=(u["full_name"] or "").strip() or u["username"],
                           photo=_pphoto())
