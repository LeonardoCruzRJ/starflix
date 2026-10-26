#!/usr/bin/env bash
# Gera o APK release assinado em ./starflix.apk (requer JDK 17 e Android SDK: ANDROID_HOME ou android/local.properties).
set -euo pipefail
cd "$(dirname "$0")/../android"

if [ ! -f keystore.properties ]; then
  PASS=$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 20)
  keytool -genkeypair -v -keystore starflix.jks -alias starflix -keyalg RSA -keysize 2048 -validity 10000 \
    -storepass "$PASS" -keypass "$PASS" -dname "CN=StarFlix"
  printf 'storeFile=starflix.jks\nstorePassword=%s\nkeyAlias=starflix\nkeyPassword=%s\n' "$PASS" "$PASS" > keystore.properties
fi

./gradlew assembleRelease
cp app/build/outputs/apk/release/app-release.apk ../starflix.apk
echo "APK: $(cd .. && pwd)/starflix.apk"
