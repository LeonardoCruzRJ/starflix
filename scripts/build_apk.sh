#!/usr/bin/env bash
# 63.1: o script de compilação agora fica na raiz do projeto (./build_apk.sh); este atalho só o chama.
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/build_apk.sh" "$@"
