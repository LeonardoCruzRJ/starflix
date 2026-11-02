#!/usr/bin/env bash
# 63.1: compila o APK release assinado no próprio servidor Linux.
# Uso: ./build_apk.sh   (na raiz do projeto)
# Na primeira execução instala o que faltar (JDK 17 e Android SDK). A versão vem de config.VERSION (1.0.719 -> versionCode 719).
# Keystore: usa android/starflix.jks + android/keystore.properties se existirem; se não existirem, cria na 1ª execução (a MESMA chave do app instalado é necessária para atualizar por cima).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
mkdir -p apk
exec > >(tee -a apk/build.log) 2>&1
echo "=== build_apk.sh $(date '+%F %T') ==="
trap 'echo "ERRO: o script parou na linha $LINENO (comando: $BASH_COMMAND). Log: $ROOT/apk/build.log"' ERR

# uma compilação por vez
exec 9>apk/.build.lock
flock -n 9 || { echo "ERRO: já existe uma compilação em andamento."; exit 1; }

SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
apt_install() { $SUDO apt-get update -y && $SUDO apt-get install -y "$@"; }

# versão (fonte única: config.VERSION)
VERSION="$(python3 -c 'import config; print(config.VERSION)' 2>/dev/null || sed -n 's/^VERSION *= *"\([^"]*\)".*/\1/p' config.py | head -1)"
[ -n "$VERSION" ] || { echo "ERRO: não achei VERSION em config.py"; exit 1; }
CODE="${VERSION##*.}"
case "$CODE" in ''|*[!0-9]*) echo "ERRO: VERSION '$VERSION' precisa terminar em número (ex.: 1.0.719)"; exit 1;; esac
echo "Versão: $VERSION (versionCode $CODE)"

# JDK 17
java_major() { java -version 2>&1 | sed -n 's/.*version "\([0-9]*\).*/\1/p' | head -1; }
if ! command -v java >/dev/null 2>&1 || [ "$(java_major)" != "17" ]; then
  echo "JDK 17 não encontrado: instalando (apt)..."
  apt_install openjdk-17-jdk-headless
fi
if [ "$(java_major)" != "17" ]; then
  J="$(ls -d /usr/lib/jvm/*17*/ 2>/dev/null | head -1 || true)"
  [ -n "$J" ] || { echo "ERRO: JDK 17 indisponível."; exit 1; }
  export JAVA_HOME="${J%/}"; export PATH="$JAVA_HOME/bin:$PATH"
fi
echo "JDK: $(java -version 2>&1 | head -1)"

# keystore: se android/starflix.jks e android/keystore.properties existem, usa e pula a criação; se nenhum existe, cria na 1ª vez
JKS=android/starflix.jks; KSP=android/keystore.properties
if [ -f "$JKS" ] && [ -f "$KSP" ]; then
  echo "Keystore encontrada: usando a existente."
elif [ ! -f "$JKS" ] && [ ! -f "$KSP" ]; then
  echo "Keystore não encontrada: criando uma nova (guarde android/starflix.jks e android/keystore.properties)."
  echo "AVISO: app já instalado com outra chave não atualiza por cima; copie os dois arquivos do Windows para android/ antes, se for o caso."
  PASS="$(python3 -c 'import secrets; print(secrets.token_hex(10))')"
  keytool -genkeypair -keystore "$JKS" -alias starflix -keyalg RSA -keysize 2048 -validity 10000 \
    -storepass "$PASS" -keypass "$PASS" -dname "CN=StarFlix"
  printf 'storeFile=starflix.jks\nstorePassword=%s\nkeyAlias=starflix\nkeyPassword=%s\n' "$PASS" "$PASS" > "$KSP"
  chmod 600 "$KSP" "$JKS"
else
  echo "ERRO: só existe um dos dois arquivos (android/starflix.jks e android/keystore.properties). Copie o que falta ou apague o que sobrou para criar uma chave nova."
  exit 1
fi

# Android SDK
SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
if [ -z "$SDK" ] && [ -f android/local.properties ]; then
  SDK="$(sed -n 's/^sdk\.dir=//p' android/local.properties | head -1)"
fi
[ -n "$SDK" ] || SDK="$HOME/android-sdk"
SDKM="$SDK/cmdline-tools/latest/bin/sdkmanager"
if [ ! -x "$SDKM" ]; then
  echo "Android SDK não encontrado em $SDK: baixando as ferramentas de linha de comando..."
  command -v curl >/dev/null 2>&1 && command -v unzip >/dev/null 2>&1 || apt_install curl unzip
  TMP="$(mktemp -d)"
  curl -fL -o "$TMP/cmdline.zip" "https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip"
  mkdir -p "$SDK/cmdline-tools"
  unzip -q "$TMP/cmdline.zip" -d "$TMP"
  rm -rf "$SDK/cmdline-tools/latest"
  mv "$TMP/cmdline-tools" "$SDK/cmdline-tools/latest"
  rm -rf "$TMP"
fi
export ANDROID_HOME="$SDK"; export ANDROID_SDK_ROOT="$SDK"
if [ ! -d "$SDK/platforms/android-34" ] || [ ! -d "$SDK/build-tools/34.0.0" ]; then
  echo "Instalando plataforma 34 e build-tools 34.0.0..."
  yes | "$SDKM" --sdk_root="$SDK" --licenses >/dev/null 2>&1 || true
  "$SDKM" --sdk_root="$SDK" "platforms;android-34" "build-tools;34.0.0"
fi
printf 'sdk.dir=%s\n' "$SDK" > android/local.properties

# compila
cd android
chmod +x gradlew
./gradlew --no-daemon assembleRelease -PsfVersionName="$VERSION" -PsfVersionCode="$CODE"
cd "$ROOT"

# 63.2: confere o APK antes de publicar (assinatura, pacote e versionCode); se falhar, apk/ fica como estava
BUILT=android/app/build/outputs/apk/release/app-release.apk
BT="$SDK/build-tools/34.0.0"
[ -f "$BUILT" ] || { echo "ERRO: o Gradle não gerou $BUILT"; exit 1; }
"$BT/apksigner" verify "$BUILT" || { echo "ERRO: assinatura do APK inválida (apk/ não foi alterado)."; exit 1; }
BADGE="$("$BT/aapt2" dump badging "$BUILT")"; BADGE="${BADGE%%$'\n'*}"  # sem "| head -1": com pipefail o SIGPIPE do aapt2 matava o script em silêncio
case "$BADGE" in
  *"name='com.starflix.app'"*"versionCode='$CODE'"*) ;;
  *) echo "ERRO: pacote/versionCode do APK não conferem com $CODE: $BADGE (apk/ não foi alterado)."; exit 1;;
esac

# publica: APK e version.json novos ao lado, depois trocados em seguida (o json por último, só aponta para APK já no lugar)
cp "$BUILT" apk/starflix.apk.new
python3 - "$VERSION" "$CODE" <<'PY'
import hashlib, json, os, sys, datetime
v, c = sys.argv[1], int(sys.argv[2])
p = "apk/starflix.apk.new"
h = hashlib.sha256(open(p, "rb").read()).hexdigest()
info = {"app": "starflix", "versionCode": c, "versionName": v, "file": "starflix.apk",
        "size": os.path.getsize(p), "sha256": h,
        "built_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
open("apk/version.json.new", "w", encoding="utf-8").write(json.dumps(info, indent=2) + "\n")
PY
mv -f apk/starflix.apk.new apk/starflix.apk
mv -f apk/version.json.new apk/version.json
echo "APK: $ROOT/apk/starflix.apk (versão $VERSION)"
echo "Versão publicada: $ROOT/apk/version.json"
