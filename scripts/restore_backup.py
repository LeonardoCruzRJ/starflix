#!/usr/bin/env python3
"""Restaura um backup (51.4) feito pelo Painel. Rode FORA do servidor, com o serviço parado:

    sudo systemctl stop starflix
    python3 scripts/restore_backup.py data/backups/starflix-AAAAMMDD-HHMMSS.zip
    sudo systemctl start starflix

O banco atual vira data/starflix.db.antes-restore e as fotos atuais, data/avatars.antes-restore (a cópia anterior, se houver, é substituída).
Use --force só se tiver certeza de que o servidor está parado (o teste da porta salva em Configurações → Servidor pode falhar numa porta diferente)."""
import os
import re
import shutil
import socket
import sqlite3
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import config  # noqa: E402  (só lê variáveis de ambiente e caminhos; não abre o banco)

AVATAR = re.compile(r"^avatars/[^/\\]+$")


def die(msg):
    print("ERRO:", msg)
    sys.exit(1)


def server_port():
    """60.1: porta salva em Configurações → Servidor (banco atual); sem banco ou sem valor, 32000."""
    try:
        r = sqlite3.connect("file:" + config.DB_PATH + "?mode=ro", uri=True).execute("SELECT value FROM settings WHERE key = 'server_port'").fetchone()
        p = int(r[0]) if r else 0
    except (sqlite3.Error, ValueError, TypeError):
        p = 0
    return p if 1024 <= p <= 65535 else config.DEFAULT_PORT


def server_running():
    s = socket.socket()
    s.settimeout(1)
    try:
        return s.connect_ex(("127.0.0.1", server_port())) == 0
    finally:
        s.close()


def main(argv):
    force = "--force" in argv
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        die("uso: python3 scripts/restore_backup.py <arquivo.zip> [--force]")
    src = args[0]
    if not zipfile.is_zipfile(src):
        die("não é um arquivo zip válido: " + src)
    if not force and server_running():
        die(f"o servidor parece estar ligado (porta {server_port()} responde). Pare com: sudo systemctl stop starflix")
    with zipfile.ZipFile(src) as z:
        names = z.namelist()
        if "starflix.db" not in names:
            die("o zip não tem starflix.db")
        bad = [n for n in names if n != "starflix.db" and not AVATAR.match(n)]
        if bad:
            die("entrada inesperada no zip: " + bad[0])
        if z.testzip():
            die("o zip está corrompido")
        tmp = config.DB_PATH + ".restore"
        with z.open("starflix.db") as f, open(tmp, "wb") as out:
            shutil.copyfileobj(f, out)
        try:
            con = sqlite3.connect(tmp)
            try:
                ok = con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                has_users = bool(con.execute("SELECT name FROM sqlite_master WHERE name = 'users'").fetchone())
            finally:
                con.close()
        except sqlite3.Error as e:
            os.remove(tmp)
            die("banco do backup ilegível: " + str(e))
        if not ok or not has_users:
            os.remove(tmp)
            die("o banco do backup não passou na verificação (integrity_check)")
        new_avatars = [n for n in names if n != "starflix.db"]
        # tudo conferido: agora troca
        if os.path.exists(config.DB_PATH):
            shutil.copy2(config.DB_PATH, config.DB_PATH + ".antes-restore")
        for suf in ("-wal", "-shm"):
            if os.path.exists(config.DB_PATH + suf):
                os.remove(config.DB_PATH + suf)
        os.replace(tmp, config.DB_PATH)
        old_av = config.AVATARS_DIR + ".antes-restore"
        if os.path.isdir(config.AVATARS_DIR):
            shutil.rmtree(old_av, ignore_errors=True)
            os.replace(config.AVATARS_DIR, old_av)
        os.makedirs(config.AVATARS_DIR, exist_ok=True)
        for n in new_avatars:
            with z.open(n) as f, open(os.path.join(config.AVATARS_DIR, os.path.basename(n)), "wb") as out:
                shutil.copyfileobj(f, out)
    print(f"Restaurado: banco e {len(new_avatars)} foto(s) de perfil.")
    print("O banco anterior ficou em", config.DB_PATH + ".antes-restore")
    print("Agora suba o servidor: sudo systemctl start starflix")


if __name__ == "__main__":
    main(sys.argv[1:])
