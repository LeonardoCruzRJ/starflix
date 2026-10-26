#!/usr/bin/env python3
"""59.27: gera os recursos de texto do Android a partir de i18n/*.json (fonte única). Nunca editar os arquivos gerados à mão.
A partir da pasta do projeto: python3 scripts/i18n_build.py [--check] [--dry-run] [--i18n PASTA] [--res PASTA]

Entrada: só as chaves `android.*` (ex.: `android.connect.title` vira `connect_title`; o prefixo `android.` sai, `.` e `-` viram `_`).
Saída (pt-BR é o padrão, sem qualificador):
  <res>/values/strings.xml           pt-BR
  <res>/values-<idioma>/strings.xml  en, es, ru, fr, de, it, ja, zh, tr
  <res>/xml/locales_config.xml       lista de idiomas do app (Android 13+, usada pela 59.29)
Plurais: chaves `x.one/.few/.many/.other` (também .zero/.two) viram `<plurals name="x">` com `<item quantity=...>`.
Variáveis: `{n}` vira `%1$d` (número, para `getQuantityString`/contagens); qualquer outra `{nome}` vira `%N$s`. A posição N segue a ordem de
primeira aparição no texto pt-BR da mesma chave, igual em todos os idiomas (a tradução pode reordenar as variáveis sem quebrar).
Chave que falta num idioma é omitida (o Android cai no padrão pt-BR). Sem nenhuma chave `android.*` em pt-BR nada é escrito
(não apaga o `strings.xml` atual). `--check` sai com 1 se algum arquivo gerado difere do disco; `--dry-run` não grava."""
import argparse, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "pt-BR"
# código do catálogo -> pasta de valores (None = padrão)
FOLDERS = {"pt-BR": None, "en-US": "en", "es-ES": "es", "ru-RU": "ru", "fr-FR": "fr", "de-DE": "de", "it-IT": "it",
           "ja-JP": "ja", "zh-CN": "zh", "tr-TR": "tr"}
CATS = ("zero", "one", "two", "few", "many", "other")
VAR = re.compile(r"\{(\w+)\}")
HEAD = "<!-- GERADO por scripts/i18n_build.py a partir de i18n/*.json (chaves android.*). Não edite à mão. -->"


def load(i18n, code):
    p = i18n / f"{code}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def res_name(key):
    return re.sub(r"[^a-z0-9_]", "_", key[len("android."):].lower())


def split_plural(key):
    m = re.match(r"^(.*)\.(zero|one|two|few|many|other)$", key)
    return (m.group(1), m.group(2)) if m else (key, None)


def var_order(text):
    out = []
    for v in VAR.findall(text):
        if v not in out:
            out.append(v)
    return out


def xml_text(s, order):
    """Escapa para strings.xml do Android e troca {var} por %N$d / %N$s."""
    has_vars = bool(order)
    s = s.replace("\\", "\\\\").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = s.replace("'", "\\'").replace('"', '\\"').replace("\n", "\\n")
    if has_vars:
        s = s.replace("%", "%%")
        s = VAR.sub(lambda m: "%%%d$%s" % (order.index(m.group(1)) + 1, "d" if m.group(1) == "n" else "s") if m.group(1) in order else m.group(0), s)
    if s[:1] in ("@", "?"):
        s = "\\" + s
    return s


def build(i18n):
    src = {k: v for k, v in load(i18n, SRC).items() if k.startswith("android.")}
    if not src:
        return None
    # estrutura em pt-BR: nome -> ("s", chave) ou ("p", [cats])
    names, order_of = [], {}
    seen = set()
    for k in src:
        base, cat = split_plural(k)
        rn = res_name(base) if cat else res_name(k)
        if rn in seen:
            continue
        seen.add(rn)
        if cat:
            names.append((rn, "p", base))
            forms = [c for c in CATS if f"{base}.{c}" in src]
            ref = src.get(f"{base}.other") or src[f"{base}.{forms[0]}"]
            order_of[rn] = var_order(ref)
        else:
            names.append((rn, "s", k))
            order_of[rn] = var_order(src[k])
    files = {}
    for code, folder in FOLDERS.items():
        cat = load(i18n, code)
        lines = ['<?xml version="1.0" encoding="utf-8"?>', HEAD, "<resources>"]
        for rn, kind, key in names:
            order = order_of[rn]
            if kind == "s":
                if key not in cat:
                    continue
                txt = cat[key]
                attr = ' formatted="false"' if ("%" in txt and not order) else ""
                lines.append(f'    <string name="{rn}"{attr}>{xml_text(txt, order)}</string>')
            else:
                items = [(c, cat[f"{key}.{c}"]) for c in CATS if f"{key}.{c}" in cat]
                if not items:
                    continue
                lines.append(f'    <plurals name="{rn}">')
                for c, txt in items:
                    lines.append(f'        <item quantity="{c}">{xml_text(txt, order)}</item>')
                lines.append("    </plurals>")
        lines.append("</resources>")
        rel = "values/strings.xml" if folder is None else f"values-{folder}/strings.xml"
        files[rel] = "\n".join(lines) + "\n"
    loc = ['<?xml version="1.0" encoding="utf-8"?>', HEAD, "<locale-config xmlns:android=\"http://schemas.android.com/apk/res/android\">"]
    loc += [f'    <locale android:name="{c}"/>' for c in FOLDERS]
    loc.append("</locale-config>")
    files["xml/locales_config.xml"] = "\n".join(loc) + "\n"
    return files


def main():
    ap = argparse.ArgumentParser(description="gera strings.xml do Android a partir de i18n/*.json")
    ap.add_argument("--check", action="store_true", help="sai com 1 se um arquivo gerado difere do disco")
    ap.add_argument("--dry-run", action="store_true", help="não grava nada")
    ap.add_argument("--i18n", default=str(ROOT / "i18n"))
    ap.add_argument("--res", default=str(ROOT / "android/app/src/main/res"))
    a = ap.parse_args()
    files = build(Path(a.i18n))
    if files is None:
        print("i18n_build: nenhuma chave android.* em pt-BR; nada gerado (strings.xml atual preservado)")
        return 0
    res = Path(a.res)
    diff = 0
    for rel, text in files.items():
        p = res / rel
        same = p.exists() and p.read_text(encoding="utf-8") == text
        if not same:
            diff += 1
        if not a.check and not a.dry_run and not same:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
    print(f"i18n_build: {len(files)} arquivos, {diff} {'diferem' if a.check or a.dry_run else 'gravados'}")
    return 1 if (a.check and diff) else 0


if __name__ == "__main__":
    sys.exit(main())
