#!/usr/bin/env bash
# StarFlix — instalador único: baixa, instala dependências e cria o serviço systemd.
# Uso:  curl -fsSL https://raw.githubusercontent.com/LeonardoCruzRJ/starflix/main/install.sh | sudo bash
# Variáveis opcionais: STARFLIX_DIR (padrão /data/starflix), STARFLIX_REPO, STARFLIX_BRANCH (padrão main)
# Rodar de novo atualiza o código e reinicia o serviço (data/ e scripts/.env são preservados).
set -euo pipefail

DIR="${STARFLIX_DIR:-/data/starflix}"
REPO="${STARFLIX_REPO:-https://github.com/LeonardoCruzRJ/starflix.git}"
BRANCH="${STARFLIX_BRANCH:-main}"
SERVICE="starflix"
PORT=32000

say() { printf '\n\033[1;33m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
die() { printf '\033[1;31mErro:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "execute como root (sudo)."
command -v apt-get >/dev/null || die "este instalador suporta Debian/Ubuntu (apt)."
command -v systemctl >/dev/null || die "systemd não encontrado."

say "Instalando pacotes (git, python3, pip, ffmpeg, curl)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git python3 python3-pip ffmpeg curl ca-certificates >/dev/null

# 60.14: a pasta imagens/ (figuras do README, só para o GitHub) não vai para a máquina: fica fora do checkout (sparse-checkout) e, no clone novo,
# nem os arquivos são baixados (--filter=blob:none). Arquivo escrito à mão em .git/info/sparse-checkout: funciona em qualquer git, antigo ou novo.
no_images() {
  git -C "$DIR" config core.sparseCheckout true
  mkdir -p "$DIR/.git/info"
  printf '/*\n!/imagens/\n' > "$DIR/.git/info/sparse-checkout"
}

say "Baixando o StarFlix em $DIR"
if [ -d "$DIR/.git" ]; then
  no_images
  git -C "$DIR" read-tree -mu HEAD 2>/dev/null || true
  git -C "$DIR" fetch --quiet origin "$BRANCH"
  git -C "$DIR" checkout --quiet "$BRANCH"
  git -C "$DIR" pull --quiet --ff-only origin "$BRANCH"
elif [ -e "$DIR" ] && [ -n "$(ls -A "$DIR" 2>/dev/null)" ]; then
  die "$DIR já existe e não é um repositório do StarFlix."
else
  mkdir -p "$(dirname "$DIR")"
  git clone --quiet --no-checkout --filter=blob:none --branch "$BRANCH" "$REPO" "$DIR" 2>/dev/null \
    || git clone --quiet --no-checkout --branch "$BRANCH" "$REPO" "$DIR"
  no_images
  git -C "$DIR" checkout --quiet -f "$BRANCH"
fi
cd "$DIR"

say "Instalando dependências Python"
if ! pip3 install --quiet --break-system-packages -r requirements.txt 2>/dev/null; then
  pip3 install --quiet -r requirements.txt
fi

say "Preparando pastas e configuração"
mkdir -p data/{posters,transcode,subs,avatars,backups}
[ -f scripts/.env ] || touch scripts/.env

say "Criando o serviço systemd"
sed "s|@DIR@|$DIR|g" scripts/starflix.service > "/etc/systemd/system/$SERVICE.service"
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null 2>&1
systemctl restart "$SERVICE"

# 60.1: a porta pode ter sido trocada em Configurações → Servidor (guardada no banco); sem valor, 32000
PORT="$(python3 - <<'PY' 2>/dev/null || echo 32000
import sqlite3
try:
    r = sqlite3.connect("file:data/starflix.db?mode=ro", uri=True).execute("SELECT value FROM settings WHERE key = 'server_port'").fetchone()
    p = int(r[0]) if r else 0
except Exception:
    p = 0
print(p if 1024 <= p <= 65535 else 32000)
PY
)"

say "Aguardando o servidor subir"
for _ in $(seq 1 30); do
  curl -fs "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && ok=1 && break
  sleep 1
done
[ "${ok:-0}" = 1 ] || die "o serviço não respondeu. Veja: journalctl -u $SERVICE -n 50"

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
VER="$(python3 -c 'import config; print(config.VERSION)' 2>/dev/null || echo '?')"
printf '\n\033[1;32m✔ StarFlix %s instalado e rodando.\033[0m\n' "$VER"
printf '  Acesse:  http://%s:%s\n' "${IP:-IP-DO-SERVIDOR}" "$PORT"
printf '  Logs:    journalctl -u %s -f\n' "$SERVICE"
printf '  Atualizar: execute este instalador novamente.\n\n'
