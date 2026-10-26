#!/usr/bin/env python3
"""59.7: confere a internacionalização. A partir da pasta do projeto: python3 scripts/i18n_check.py [-v] [--max N] [--only PARTE]
Partes: keys (faltando/sobrando por idioma), vars (placeholders diferentes), plural (categorias CLDR), unused (chaves sem uso),
literals (texto fixo em português em templates, JS, Python e Kotlin). Saída 1 se achar algo. Exceções em i18n/allow.txt:
  file <glob>             ignora o arquivo nos literais
  lit <glob>::<trecho>    ignora o literal que contiver o trecho (no arquivo casado pelo glob)
  key <prefixo>           chave (ou prefixo) que não conta como sem uso
Linha de código com `i18n-ok` (em comentário) também é ignorada."""
import argparse, ast, fnmatch, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
I18N = ROOT / "i18n"
SRC = "pt-BR"
PLURAL = {"ru-RU": ["one", "few", "many", "other"], "ja-JP": ["other"], "zh-CN": ["other"], "pt-BR": ["one", "other"],
          "fr-FR": ["one", "other"]}
CATS = ("zero", "one", "two", "few", "many", "other")
VAR = re.compile(r"\{(\w+)\}")
ACC = re.compile(r"[áàâãäéêíóôõúüçÁÀÂÃÉÊÍÓÔÕÚÇ]")
WORD = re.compile(r"[A-Za-zÀ-ÿ]+")
GENERIC = {"para", "com", "uma", "que", "por", "dos", "das", "ao", "ou", "sem", "mais", "ele", "ela", "seu", "sua", "foi", "ser", "tem", "não", "nao"}
SPECIFIC = {"salvar", "cancelar", "apagar", "fechar", "voltar", "carregando", "erro", "biblioteca", "bibliotecas", "filmes", "séries", "series",
            "usuário", "usuários", "senha", "idioma", "configurações", "buscar", "editar", "remover", "adicionar", "assistir", "reproduzir",
            "episódio", "temporada", "legendas", "áudio", "falha", "servidor", "conectar", "entrar", "sair", "perfil", "perfis", "início"}
EXT = {".html": "tpl", ".js": "js", ".py": "py", ".kt": "kt"}
SKIP_DIRS = {"node_modules", ".git", "build", "__pycache__", "data", "static/fonts"}
SKIP_FILES = {"hls.min.js", "hls.js", "dash.all.min.js", "i18n_check.py"}


def is_pt(s):
    s = s.strip()
    if len(s) < 3 or "\n" in s and len(s) > 400:
        return False
    if re.fullmatch(r"[\w./:#?&=%+\-\[\]{}()$@!,;*|\\^~<>\"' ]*", s) and not ACC.search(s) and " " not in s:
        return False
    if ACC.search(s):
        return True
    w = [x.lower() for x in WORD.findall(s)]
    return any(x in SPECIFIC for x in w) or sum(x in GENERIC for x in w) >= 2


def load_allow():
    f, lit, key = [], [], []
    p = I18N / "allow.txt"
    if p.exists():
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.split("#", 1)[0].strip() if not ln.lstrip().startswith(("lit", "file", "key")) else ln.strip()
            if not ln:
                continue
            k, _, rest = ln.partition(" ")
            rest = rest.strip()
            if k == "file":
                f.append(rest)
            elif k == "key":
                key.append(rest)
            elif k == "lit" and "::" in rest:
                g, _, t = rest.partition("::")
                lit.append((g.strip(), t.strip()))
    return f, lit, key


def catalogs():
    out = {}
    for p in sorted(I18N.glob("*.json")):
        try:
            out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
        except ValueError as e:
            print(f"ERRO: {p.name} inválido: {e}")
            sys.exit(2)
    return out


def sources():
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT).as_posix()
        if p.suffix not in EXT or p.name in SKIP_FILES or not p.is_file():
            continue
        if any(rel.startswith(d + "/") or f"/{d}/" in rel for d in SKIP_DIRS):
            continue
        yield rel, p


# ---------- extração de literais ----------
def js_literals(src):
    """(linha, texto) de strings JS/Kotlin fora de comentários."""
    out, i, n, line = [], 0, len(src), 1
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1; i += 1
        elif src.startswith("//", i):
            j = src.find("\n", i); i = n if j < 0 else j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2); j = n if j < 0 else j + 2
            line += src.count("\n", i, j); i = j
        elif src.startswith('"""', i):  # Kotlin raw string
            j = src.find('"""', i + 3); j = n if j < 0 else j
            out.append((line, src[i + 3:j])); line += src.count("\n", i, j); i = j + 3
        elif c in "\"'`":
            j, buf = i + 1, []
            while j < n and src[j] != c:
                if src[j] == "\\" and j + 1 < n:
                    buf.append(src[j + 1]); j += 2; continue
                if src[j] == "\n" and c != "`":
                    break
                buf.append(src[j]); j += 1
            out.append((line, "".join(buf))); line += src.count("\n", i, j); i = j + 1
        else:
            i += 1
    return out


def py_literals(src):
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    skip = set()
    for nd in ast.walk(tree):
        if isinstance(nd, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and nd.body:
            b = nd.body[0]
            if isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant) and isinstance(b.value.value, str):
                skip.add(id(b.value))
    LOG = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}  # 59.19: log/print = diagnóstico do operador, não interface
    for nd in ast.walk(tree):
        if isinstance(nd, ast.Call) and ((isinstance(nd.func, ast.Attribute) and nd.func.attr in LOG and isinstance(nd.func.value, ast.Name)
                                           and nd.func.value.id in {"log", "logger", "logging", "_log", "LOG"})
                                          or (isinstance(nd.func, ast.Name) and nd.func.id == "print")):
            for sub in ast.walk(nd):
                if isinstance(sub, (ast.Constant, ast.JoinedStr)):
                    skip.add(id(sub))
                    if isinstance(sub, ast.JoinedStr):
                        skip.update(id(v) for v in ast.walk(sub))
    return [(nd.lineno, nd.value) for nd in ast.walk(tree)
            if isinstance(nd, ast.Constant) and isinstance(nd.value, str) and id(nd) not in skip]


def tpl_literals(src):
    out = []
    blank = lambda m: re.sub(r"[^\n]", " ", m.group(0))
    s = re.sub(r"\{#.*?#\}|<!--.*?-->", blank, src, flags=re.S)
    s = re.sub(r"<style\b.*?</style>", blank, s, flags=re.S | re.I)
    for m in re.finditer(r"<script\b[^>]*>(.*?)</script>", s, flags=re.S | re.I):
        base = s.count("\n", 0, m.start(1))
        out += [(base + ln, t) for ln, t in js_literals(re.sub(r"\{[{%].*?[}%]\}", blank, m.group(1), flags=re.S))]
    s = re.sub(r"<script\b.*?</script>", blank, s, flags=re.S | re.I)
    s = re.sub(r"\{\{.*?\}\}|\{%.*?%\}", blank, s, flags=re.S)
    for m in re.finditer(r">([^<>]+)<", s):
        out.append((s.count("\n", 0, m.start(1)) + 1, m.group(1)))
    for m in re.finditer(r"\b(?:title|placeholder|aria-label|alt|value|label)=\"([^\"]*)\"", s):
        out.append((s.count("\n", 0, m.start(1)) + 1, m.group(1)))
    return out


def find_literals(allow_f, allow_l):
    res = []
    for rel, p in sources():
        if any(fnmatch.fnmatch(rel, g) for g in allow_f):
            continue
        raw = p.read_text(encoding="utf-8", errors="replace")
        lines = raw.splitlines()
        kind = EXT[p.suffix]
        lits = tpl_literals(raw) if kind == "tpl" else py_literals(raw) if kind == "py" else js_literals(raw)
        for ln, t in lits:
            t = " ".join(t.split())
            if not is_pt(t):
                continue
            if 0 < ln <= len(lines) and "i18n-ok" in lines[ln - 1]:
                continue
            if any(fnmatch.fnmatch(rel, g) and x in t for g, x in allow_l):
                continue
            res.append((rel, ln, t))
    return res


# ---------- conferências do catálogo ----------
def base_key(k):
    m = re.match(r"(.+)\.(zero|one|two|few|many|other)$", k)
    return m.group(1) if m else k


def check_keys(cats):
    ref, probs = cats.get(SRC, {}), []
    for lang, c in cats.items():
        if lang == SRC:
            continue
        rb, cb = {base_key(k) for k in ref}, {base_key(k) for k in c}  # plurais por idioma: compara a chave-base
        probs += [f"{lang}: falta {k}" for k in sorted(rb - cb)]
        probs += [f"{lang}: sobra {k}" for k in sorted(cb - rb)]
    return probs


def check_vars(cats):
    ref, probs = cats.get(SRC, {}), []
    for lang, c in cats.items():
        for k, v in c.items():
            if k in ref and lang != SRC and set(VAR.findall(v)) != set(VAR.findall(ref[k])):
                probs.append(f"{lang}: {k}: variáveis {sorted(set(VAR.findall(v)))} ≠ {sorted(set(VAR.findall(ref[k])))}")
    return probs


def check_plural(cats):
    probs = []
    for lang, c in cats.items():
        need = PLURAL.get(lang, ["one", "other"])
        groups = {}
        for k in c:
            if k != base_key(k):
                groups.setdefault(base_key(k), set()).add(k.rsplit(".", 1)[1])
        for b, have in sorted(groups.items()):
            if "other" not in have:
                probs.append(f"{lang}: {b}: falta .other")
            miss = [x for x in need if x not in have]
            if miss and lang != SRC:
                probs.append(f"{lang}: {b}: faltam .{', .'.join(miss)}")
            extra = [x for x in have if x not in need and x in CATS]
            if extra:
                probs.append(f"{lang}: {b}: categoria sem uso no idioma: .{', .'.join(extra)}")
    return probs


def check_unused(cats, allow_k):
    blob = "\n".join(p.read_text(encoding="utf-8", errors="replace") for _, p in sources())
    used = set(re.findall(r"[\"'`]([a-z][\w]*(?:\.[\w]+)+)[\"'`]", blob))
    used |= set(re.findall(r"data-i18n(?:-\w+)?=\"([^\"]+)\"", blob))
    keys = {base_key(k) for c in cats.values() for k in c}
    return [f"{k}" for k in sorted(keys) if k not in used and not k.startswith("android.")
            and not any(k == a or k.startswith(a) for a in allow_k)]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-v", "--verbose", action="store_true", help="lista tudo (sem limite)")
    ap.add_argument("--max", type=int, default=15, help="itens listados por parte (padrão 15)")
    ap.add_argument("--only", choices=["keys", "vars", "plural", "unused", "literals"])
    a = ap.parse_args()
    cats = catalogs()
    if SRC not in cats:
        print(f"ERRO: i18n/{SRC}.json não existe"); return 2
    allow_f, allow_l, allow_k = load_allow()
    parts = {
        "keys": ("chaves faltando/sobrando", lambda: check_keys(cats)),
        "vars": ("placeholders diferentes", lambda: check_vars(cats)),
        "plural": ("plurais", lambda: check_plural(cats)),
        "unused": ("chaves sem uso", lambda: check_unused(cats, allow_k)),
        "literals": ("literais fixos em português", lambda: [f"{r}:{l}: {t[:90]}" for r, l, t in find_literals(allow_f, allow_l)]),
    }
    print(f"idiomas: {', '.join(cats)} · chaves em {SRC}: {len(cats[SRC])}")
    total = 0
    for k, (nome, fn) in parts.items():
        if a.only and a.only != k:
            continue
        r = fn(); total += len(r)
        print(f"[{'OK' if not r else len(r)}] {nome}")
        for x in (r if a.verbose else r[:a.max]):
            print("   ", x)
        if not a.verbose and len(r) > a.max:
            print(f"    … +{len(r) - a.max} (use -v)")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
