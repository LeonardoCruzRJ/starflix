#!/usr/bin/env bash
# 62.1/62.10: empacota o canal Roku (pasta roku/).
#   ./scripts/build_roku.sh                    gera ./starflix-roku.zip (instalação pelo modo desenvolvedor)
#   ./scripts/build_roku.sh --install IP SENHA envia o zip para a Roku (plugin_install; precisa do curl)
#   ./scripts/build_roku.sh --pkg IP SENHA SENHA_DA_CHAVE   gera o .pkg assinado e o baixa para ./starflix-roku.pkg
# Para o --pkg (4º argumento = senha da chave) é preciso ter rodado `genkey` antes: roku/README.md, "Pacote .pkg".
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="starflix-roku.zip"

# confere o canal antes de empacotar: arquivos citados nos XML/manifest existem e as versões batem
python3 - <<'PY'
import re, sys, pathlib
r = pathlib.Path("roku"); bad = []
for f in list(r.glob("components/*.xml")):
    for u in re.findall(r'uri="pkg:/([^"]+)"', f.read_text(encoding="utf-8")):
        if not (r / u).exists(): bad.append(f"{f.name}: {u}")
man = (r / "manifest").read_text(encoding="utf-8")
for u in re.findall(r"=pkg:/(\S+)", man):
    if not (r / u).exists(): bad.append(f"manifest: {u}")
ver = re.search(r'VERSION = "1\.0\.(\d+)"', pathlib.Path("config.py").read_text(encoding="utf-8")).group(1)
if f"build_version={ver}" not in man: bad.append(f"manifest: build_version diferente de config.VERSION ({ver})")
for f in list(r.glob("components/*.brs")) + list(r.glob("source/*.brs")):
    t = re.sub(r"'.*", "", f.read_text(encoding="utf-8"))
    n = lambda p: len(re.findall(p, t, re.M | re.I))
    if n(r"^\s*(?:sub|function)\s") != n(r"^\s*end\s+(?:sub|function)\b"): bad.append(f"{f.name}: sub/function sem end")
    res = r"(?:pos|next|run|step|stop|tab|let|rem|goto|print|eval|line_num|dim)"  # palavras reservadas do BrightScript (o emulador recusa)
    for mm in re.finditer(rf"^\s*{res}\s*=[^=]|^\s*(?:sub|function)\s+{res}\s*\(|[(,]\s*{res}\s+as\s|for\s+each\s+{res}\b", t, re.M | re.I):
        bad.append(f"{f.name}: palavra reservada como nome: {mm.group(0).strip()}")
if bad:
    print("ERRO:\n  " + "\n  ".join(bad)); sys.exit(1)
PY

build_zip() {
    rm -f "$OUT"
    (cd roku
     if command -v zip >/dev/null 2>&1; then
         zip -qr "../$OUT" manifest source components images -x '*.DS_Store'
     else
         python3 -m zipfile -c "../$OUT" manifest source components images
     fi)
}

case "${1:-}" in
    --install)
        build_zip
        curl -sS --digest -u "rokudev:${3:?senha}" -F mysubmit=Install -F "archive=@$OUT" "http://${2:?ip}/plugin_install" | grep -io 'install success\|identical to previous\|failed[^<]*' | head -1
        ;;
    --pkg)
        build_zip
        IP="${2:?ip}"; PW="${3:?senha}"
        curl -sS --digest -u "rokudev:$PW" -F mysubmit=Install -F "archive=@$OUT" "http://$IP/plugin_install" >/dev/null
        PAGE=$(curl -sS --digest -u "rokudev:$PW" -F mysubmit=Package -F "app_name=StarFlix/1.0" -F "passwd=${4:?senha da chave (genkey)}" -F "pkg_time=$(date +%s)" "http://$IP/plugin_package")
        PKG=$(printf '%s' "$PAGE" | grep -o 'pkgs/[^"]*\.pkg' | head -1)
        [ -n "$PKG" ] || { echo "Falha ao gerar o .pkg (genkey feito? senha da chave certa?)"; exit 1; }
        curl -sS --digest -u "rokudev:$PW" -o starflix-roku.pkg "http://$IP/$PKG"
        echo "Gerado: starflix-roku.pkg"
        ;;
    *)
        build_zip
        echo "Gerado: $OUT"
        ;;
esac
