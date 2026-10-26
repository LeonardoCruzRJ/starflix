"""31.2: motor de regras dos filtros avançados / coleções e listas inteligentes.

Spec: {"match": "all|any", "rules": [{"field", "op", "value"}], "limit": int|None}
"""
import json
import math
from datetime import datetime

from flask import Blueprint, jsonify, request, session

from server.auth import login_required
from server.db import fold, get_db
from server.libraries import _items, _get_lib
from server.i18n import E, jerr

bp = Blueprint("smart", __name__)

TEXT_OPS = {"contains", "not_contains", "is", "is_not"}
NUM_OPS = {"is", "is_not", "gt", "lt"}
FIELDS = {  # campo -> (rótulo, tipo, operadores)
    "title": ("adv.field.title", "text", TEXT_OPS),
    "year": ("adv.field.year", "num", NUM_OPS),
    "genre": ("adv.field.genre", "text", TEXT_OPS),
    "watched": ("adv.field.watched", "bool", {"is", "is_not"}),
    "added": ("adv.field.added", "date", {"before", "after"}),
    "rating": ("adv.field.rating", "num", {"gt", "lt"}),
}
MAX_RULES = 20
MAX_LIMIT = 10000


class SpecError(ValueError):
    pass


def _num(v):
    try:
        n = float(str(v).strip().replace(",", "."))
    except ValueError:
        raise SpecError(E("err.valor_numerico_invalido"))
    if not math.isfinite(n):
        raise SpecError(E("err.valor_numerico_invalido"))
    return n


def parse_spec(data):
    """Valida e normaliza o spec; levanta SpecError (→ 400 JSON)."""
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise SpecError(E("err.regras_invalidas"))
    match = data.get("match", "all")
    if match not in ("all", "any"):
        raise SpecError(E("err.correspondencia_invalida"))
    rules = data.get("rules", [])
    if not isinstance(rules, list) or len(rules) > MAX_RULES:
        raise SpecError(E("err.regras_invalidas"))
    out = []
    for r in rules:
        if not isinstance(r, dict):
            raise SpecError(E("err.regra_invalida"))
        field, op, val = r.get("field"), r.get("op"), r.get("value")
        if field not in FIELDS:
            raise SpecError(E("err.campo_invalido"))
        _, kind, ops = FIELDS[field]
        if op not in ops:
            raise SpecError(E("err.operador_invalido_este_campo"))
        if isinstance(val, bool) or not isinstance(val, (str, int, float)):
            raise SpecError(E("err.valor_invalido"))
        val = str(val).strip()
        if len(val) > 200:
            raise SpecError(E("err.valor_muito_longo"))
        if kind == "num":
            val = _num(val)
        elif kind == "date":
            try:
                datetime.strptime(val, "%Y-%m-%d")
            except ValueError:
                raise SpecError(E("err.data_invalida_use_aaaa_mm"))
        elif kind == "bool":
            if val not in ("0", "1"):
                raise SpecError(E("err.valor_invalido"))
        elif not val:
            raise SpecError(E("err.informe_valor"))
        out.append({"field": field, "op": op, "value": val})
    limit = data.get("limit")
    if limit in (None, ""):
        limit = None
    else:
        if isinstance(limit, bool):
            raise SpecError(E("err.limite_invalido"))
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise SpecError(E("err.limite_invalido"))
        if not 1 <= limit <= MAX_LIMIT:
            raise SpecError(E("err.limite_invalido"))
    return {"match": match, "rules": out, "limit": limit}


def _test(rule, item, extra):
    f, op, v = rule["field"], rule["op"], rule["value"]
    if f == "title":
        a, b = fold(item["title"]), fold(v)
        res = {"contains": b in a, "not_contains": b not in a, "is": a == b, "is_not": a != b}
        return res[op]
    if f == "genre":
        gs = [fold(g) for g in item["genres"]]
        b = fold(v)
        res = {"contains": any(b in g for g in gs), "not_contains": not any(b in g for g in gs),
               "is": b in gs, "is_not": b not in gs}
        return res[op]
    if f == "watched":
        return (item["watched"] == (v == "1")) == (op == "is")
    if f == "year":
        a = item["year"]
        if a is None:
            return op == "is_not"
        return {"is": a == v, "is_not": a != v, "gt": a > v, "lt": a < v}[op]
    if f == "rating":
        a = extra["rating"]
        return a is not None and (a > v if op == "gt" else a < v)
    if f == "added":
        a = (extra["added"] or "")[:10]
        return bool(a) and (a < v if op == "before" else a > v)
    return False


def _extra(lid):
    """Campos que `_items` não devolve: nota e data de adição (último episódio, como a ordenação \"Adicionado em\")."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, rating, COALESCE((SELECT MAX(e.added_at) FROM episodes e WHERE e.media_id = media.id), added_at) AS added "
            "FROM media WHERE library_id = ?", (lid,)).fetchall()
    return {r["id"]: {"rating": r["rating"], "added": r["added"]} for r in rows}


def smart_items(lid, lib_type, spec):
    """Itens da biblioteca (formato de `_items`, ordenados por título) que casam com o spec, já com o limite."""
    items = _items(lid, lib_type, "title", "asc", "all", "")
    rules = spec["rules"]
    if rules:
        extra = _extra(lid)
        pick = all if spec["match"] == "all" else any
        items = [i for i in items if pick(_test(r, i, extra.get(i["id"], {"rating": None, "added": None})) for r in rules)]
    if spec["limit"]:
        items = items[:spec["limit"]]
    return items


@bp.route("/library/<int:lid>/smart/preview")
@login_required
def preview(lid):
    """Pré-visualização ao vivo: `?spec=<JSON>` → ids e total (só biblioteca com acesso)."""
    lib = _get_lib(lid)
    try:
        raw = request.args.get("spec", "")
        spec = parse_spec(json.loads(raw) if raw else None)
    except ValueError as e:  # SpecError e JSON inválido
        return jerr(e if isinstance(e, SpecError) else E("err.regras_invalidas"), 400)
    ids = [i["id"] for i in smart_items(lid, lib["type"], spec)]
    return jsonify(ids=ids, total=len(ids))
