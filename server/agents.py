"""59.37: o idioma dos agentes (TMDB, TVDB, SubDL) não é mais escolhido aqui: segue o idioma do usuário (server/meta_lang.py).
46.1: agente SubDL (legendas): chave como os demais.
45.5: página Agentes (/admin/agents) — chaves de API do TMDB, TVDB, OMDB e SubDL guardadas no banco (tabela settings), não mais no .env.
Salvar já vale na hora: o valor é gravado em `config` (lido a cada uso pelos módulos) e o token em cache do TVDB é descartado.
Na 1ª partida com chaves ainda no ambiente/.env elas são copiadas para o banco (uma vez); depois o banco manda e o .env pode ficar sem elas."""
import os
import re

import requests
from flask import Blueprint, jsonify, render_template, request

import config
from server.auth import admin_required
from server.db import get_db
from server import meta_lang
from server.i18n import E, jerr, tr

bp = Blueprint("agents", __name__)

# id -> (atributo em config, variável de ambiente legada, nome, descrição, onde obter a chave)
AGENTS = {
    "tmdb": ("TMDB_API_KEY", "TMDB_API_KEY", "TMDB", "ag.d.tmdb",
             "https://www.themoviedb.org/settings/api"),
    "tvdb": ("TVDB_API_KEY", "TVDB_API_KEY", "TVDB", "ag.d.tvdb",
             "https://thetvdb.com/api-information"),
    "omdb": ("OMDB_API_KEY", "OMDB_API_KEY", "OMDB", "ag.d.omdb",
             "https://www.omdbapi.com/apikey.aspx"),
    "subdl": ("SUBDL_API_KEY", "SUBDL_API_KEY", "SubDL", "ag.d.subdl",
              "https://subdl.com/panel/api"),
}
_KEY_OK = re.compile(r"\S{1,200}")


def _skey(aid):
    return "api_key_" + aid


def _get(conn, aid):
    r = conn.execute("SELECT value FROM settings WHERE key = ?", (_skey(aid),)).fetchone()
    return (r["value"] or "").strip() if r else ""


def _apply(aid, value):
    """Passa a valer agora, sem reiniciar."""
    setattr(config, AGENTS[aid][0], value)
    if aid == "tvdb":
        from server import metadata
        metadata.reset_tvdb_token()  # o token em cache era da chave anterior


def load_keys():
    """Na partida: banco -> config; chave que só existe no ambiente (instalação antiga) é copiada para o banco."""
    with get_db() as conn:
        for aid, (attr, env, _n, _d, _u) in AGENTS.items():
            row = conn.execute("SELECT 1 FROM settings WHERE key = ?", (_skey(aid),)).fetchone()
            v = _get(conn, aid)
            if not row:  # nunca configurada pelo banco: aproveita a do ambiente; chave removida na página fica removida (linha vazia)
                legacy = (os.environ.get(env) or "").strip()
                if _KEY_OK.fullmatch(legacy):
                    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (_skey(aid), legacy))
                    v = legacy
            setattr(config, attr, v)
        meta_lang.load(conn)  # 59.37: idioma dos agentes = idioma escolhido pelo usuário (banco -> config)


def _mask(v):
    return "" if not v else "*" * 8 + (v[-4:] if len(v) >= 8 else "")


def _item(conn, aid):
    _a, _e, name, desc, url = AGENTS[aid]
    desc = tr(desc)
    v = _get(conn, aid)
    return {"id": aid, "name": name, "desc": desc, "url": url, "set": bool(v), "masked": _mask(v)}


def check_key(aid, key):
    """Consulta o serviço com a chave: ("ok"|"invalid"|"error", mensagem). "error" = não deu para confirmar (rede, limite, serviço fora)."""
    try:
        if aid == "tmdb":
            headers, params = {}, {}
            if key.startswith("eyJ"):  # token v4, como em metadata.tmdb_get
                headers["Authorization"] = "Bearer " + key
            else:
                params["api_key"] = key
            r = requests.get("https://api.themoviedb.org/3/authentication", params=params, headers=headers, timeout=10)
            if r.status_code == 200:
                return "ok", E("msg.chave_valida")
            if r.status_code in (401, 403):
                return "invalid", E("msg.tmdb_recusou_chave")
        elif aid == "tvdb":
            r = requests.post("https://api4.thetvdb.com/v4/login", json={"apikey": key}, timeout=10)
            if r.status_code == 200:
                return "ok", E("msg.chave_valida")
            if r.status_code in (400, 401, 403):
                return "invalid", E("msg.tvdb_recusou_chave")
        elif aid == "omdb":
            r = requests.get("https://www.omdbapi.com/", params={"apikey": key, "i": "tt0111161"}, timeout=10)
            try:
                j = r.json()
            except ValueError:
                j = {}
            if str(j.get("Response")) == "True":
                return "ok", E("msg.chave_valida")
            err = str(j.get("Error") or "")
            if "limit" in err.lower():
                return "error", E("err.limite_diario_consultas_omdb_atingido")
            if r.status_code == 401 or "invalid api key" in err.lower() or "no api key" in err.lower():
                return "invalid", E("msg.omdb_recusou_chave")
        elif aid == "subdl":  # conta da própria chave (GET /api/v1/me, documentado em "Account Status")
            r = requests.get("https://api.subdl.com/api/v1/me", params={"api_key": key}, timeout=10)
            if r.status_code in (400, 401, 403):
                return "invalid", E("msg.subdl_recusou_chave")
            if r.status_code == 200:
                try:
                    j = r.json()
                except ValueError:
                    j = {}
                if j.get("status") is False:
                    return "invalid", E("msg.subdl_recusou_chave")
                return "ok", E("msg.chave_valida")
        return "error", E("err.servico_resposta_inesperada", code=r.status_code)
    except requests.RequestException:
        return "error", E("err.nao_foi_possivel_falar_servico")


@bp.route("/admin/agents/<aid>/test", methods=["POST"])
@admin_required
def test(aid):
    """Corpo: {key} testa a chave digitada (sem salvar); sem `key` testa a chave salva."""
    if aid not in AGENTS:
        return jerr("err.agente_nao_encontrado", 404)
    d = request.get_json(silent=True)
    key = str(d.get("key", "")).strip() if isinstance(d, dict) else ""
    if not key:
        with get_db() as conn:
            key = _get(conn, aid)
    if not key:
        return jerr("err.nenhuma_chave_testar", 400)
    if not _KEY_OK.fullmatch(key):
        return jsonify(state="invalid", message=E("err.chave_sem_espacos")), 200
    state, msg = check_key(aid, key)
    return jsonify(state=state, message=msg)


@bp.route("/admin/agents")
@admin_required
def page():
    return render_template("admin_agents.html")


@bp.route("/admin/agents/data")
@admin_required
def data():
    with get_db() as conn:
        return jsonify(agents=[_item(conn, a) for a in AGENTS])


@bp.route("/admin/agents/<aid>", methods=["POST"])
@admin_required
def save(aid):
    """Corpo: {key}. A chave nunca volta na resposta. O idioma não é daqui: segue o do usuário (59.37)."""
    if aid not in AGENTS:
        return jerr("err.agente_nao_encontrado", 404)
    d = request.get_json(silent=True)
    d = d if isinstance(d, dict) else {}
    key = str(d.get("key") or "").strip()
    if key and not _KEY_OK.fullmatch(key):
        return jerr("err.chave_nao_pode_ter_espacos", 400)
    if not key:
        return jerr("err.nada_salvar", 400)
    with get_db() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (_skey(aid), key))
        item = _item(conn, aid)
    _apply(aid, key)
    if aid == "tmdb":  # as listas do TMDB do Início (por idioma/região) são baixadas em segundo plano
        try:
            from server.tmdb_lists import ensure_fresh
            ensure_fresh()
        except Exception:
            pass
    return jsonify(agent=item)


@bp.route("/admin/agents/<aid>/delete", methods=["POST"])
@admin_required
def remove(aid):
    if aid not in AGENTS:
        return jerr("err.agente_nao_encontrado", 404)
    with get_db() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES (?, '') ON CONFLICT(key) DO UPDATE SET value = ''", (_skey(aid),))
        item = _item(conn, aid)
    _apply(aid, "")
    return jsonify(agent=item)
