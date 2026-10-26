#!/usr/bin/env python3
"""Restaura um backup (51.4) feito pelo Painel. Pelo site basta o botão Restaurar (60.10); pela linha de comando, FORA do servidor, com o serviço parado:

    sudo systemctl stop starflix
    python3 scripts/restore_backup.py data/backups/starflix-AAAAMMDD-HHMMSS.zip
    sudo systemctl start starflix

Antes de mexer em qualquer coisa é feito um backup de segurança do estado atual (um zip novo em data/backups/); se a restauração falhar em qualquer ponto,
tudo volta ao estado anterior sozinho. O banco atual fica também em data/starflix.db.antes-restore e as fotos atuais, em data/avatars.antes-restore (a cópia anterior, se houver, é substituída).
Use --force só se tiver certeza de que o servidor está parado (o teste da porta salva em Configurações → Servidor pode falhar numa porta diferente).
60.10: --exec-server é o modo do botão Restaurar: o servidor troca o próprio processo por este script (execv, mesmo PID, o systemd não percebe), o script restaura e,
dando certo ou errado, troca o processo de volta pelo servidor; o resultado fica em data/restore-result.json."""
import json
import os
import re
import shutil
import socket
import sqlite3
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import config  # noqa: E402  (só lê variáveis de ambiente e caminhos; não abre o banco)

AVATAR = re.compile(r"^avatars/[^/\\]+$")


class RestoreError(Exception):
    """Falha de validação/restauração: `msg` (texto da linha de comando) e `key`/`vars` (chave do catálogo, usada pelo site)."""

    def __init__(self, msg, key="err.restore_falhou", **vars):
        super().__init__(msg)
        self.msg, self.key, self.vars = msg, key, vars


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


def validate(src):
    """Confere o zip sem mexer em nada; devolve os nomes das entradas. Levanta RestoreError."""
    if not zipfile.is_zipfile(src):
        raise RestoreError("não é um arquivo zip válido: " + src, "err.restore_zip_invalido")
    with zipfile.ZipFile(src) as z:
        names = z.namelist()
        if "starflix.db" not in names:
            raise RestoreError("o zip não tem starflix.db", "err.restore_sem_banco")
        bad = [n for n in names if n != "starflix.db" and not AVATAR.match(n)]
        if bad:
            raise RestoreError("entrada inesperada no zip: " + bad[0], "err.restore_entrada_inesperada", n=bad[0])
        if z.testzip():
            raise RestoreError("o zip está corrompido", "err.restore_zip_corrompido")
        tmp = config.DB_PATH + ".check"
        try:
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
                raise RestoreError("banco do backup ilegível: " + str(e), "err.restore_banco_ilegivel")
            if not ok or not has_users:
                raise RestoreError("o banco do backup não passou na verificação (integrity_check)", "err.restore_integridade")
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    return names


def _db_ok(path):
    """True se o banco abre, passa no integrity_check e tem a tabela `users`."""
    try:
        con = sqlite3.connect(path)
        try:
            ok = con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            has_users = bool(con.execute("SELECT name FROM sqlite_master WHERE name = 'users'").fetchone())
        finally:
            con.close()
        return ok and has_users
    except sqlite3.Error:
        return False


def _rm(path):
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.lexists(path):
            os.remove(path)
    except OSError:
        pass


def _snapshot_name():
    """starflix-AAAAMMDD-HHMMSS.zip (o mesmo padrão dos backups: aparece no Painel); se já existe, avança 1 s até achar um livre."""
    t = time.time()
    while True:
        name = time.strftime("starflix-%Y%m%d-%H%M%S.zip", time.localtime(t))
        if not os.path.exists(os.path.join(config.BACKUPS_DIR, name)):
            return name
        t += 1


def snapshot():
    """61.x: backup de segurança do estado ATUAL, feito antes de a restauração mexer em qualquer coisa.
    Deixa (1) uma cópia consistente do banco em starflix.db.antes-restore (lê o -wal; é o que a reversão usa) e (2) um zip normal em
    data/backups/ (banco + fotos), que aparece no Painel e serve de segunda rede. Se algo aqui falhar, levanta RestoreError e NADA foi alterado.
    Devolve {zip, db_copy} ou None quando não há banco atual (instalação nova: não há o que guardar)."""
    db, keep = config.DB_PATH, config.DB_PATH + ".antes-restore"
    if not os.path.exists(db):
        return None
    part_db, part_zip, final = keep + ".part", None, None
    try:
        for suf in ("", "-wal", "-shm"):
            _rm(keep + suf)
            _rm(keep + ".part" + suf)
        try:  # caminho normal: API de backup do SQLite (inclui o que ainda está no -wal)
            src = sqlite3.connect(db, timeout=30)
            try:
                dst = sqlite3.connect(part_db)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
            finally:
                src.close()
            if not _db_ok(part_db):
                raise sqlite3.DatabaseError("cópia do banco atual não passou no integrity_check")
            os.replace(part_db, keep)
        except sqlite3.Error:  # banco atual danificado (talvez seja justamente por isso que se restaura): cópia bruta dos arquivos
            _rm(part_db)
            shutil.copy2(db, keep)
            for suf in ("-wal", "-shm"):
                if os.path.exists(db + suf):
                    shutil.copy2(db + suf, keep + suf)
        os.makedirs(config.BACKUPS_DIR, exist_ok=True)
        name = _snapshot_name()
        final = os.path.join(config.BACKUPS_DIR, name)
        part_zip = final + ".part"
        _rm(part_zip)
        fd = os.open(part_zip, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # contém as chaves de API: só o dono lê
        with os.fdopen(fd, "wb") as f, zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(keep, "starflix.db")
            if os.path.isdir(config.AVATARS_DIR):
                for fn in sorted(os.listdir(config.AVATARS_DIR)):
                    p = os.path.join(config.AVATARS_DIR, fn)
                    if os.path.isfile(p):
                        z.write(p, "avatars/" + fn)
        with zipfile.ZipFile(part_zip) as z:
            if z.testzip():
                raise zipfile.BadZipFile("zip do backup de segurança corrompido")
        os.replace(part_zip, final)
        part_zip = None
        os.chmod(final, 0o600)
        return {"zip": name, "db_copy": keep}
    except Exception as e:  # disco cheio, permissão...: ainda não mexemos em nada
        for suf in ("", "-wal", "-shm"):
            _rm(keep + suf)
        if final:
            _rm(final)
        raise RestoreError("não foi possível fazer o backup de segurança antes de restaurar (nada foi alterado): " + str(e), "err.restore_backup_previo_falhou")
    finally:
        _rm(part_db)
        if part_zip:
            _rm(part_zip)


def _rollback(snap, st):
    """Devolve banco e fotos ao estado de antes da restauração. `st` diz o que já foi tocado:
    db (o banco/-wal/-shm atuais podem ter sido trocados), av_moved (fotos antigas foram para .antes-restore), av_placed (fotos novas no lugar).
    Levanta se não conseguir (quem chama avisa o usuário do backup de segurança)."""
    if st["db"]:
        if snap is None:  # não havia banco antes: tira o restaurado
            for suf in ("", "-wal", "-shm"):
                _rm(config.DB_PATH + suf)
        else:
            tmp = config.DB_PATH + ".rollback"
            _rm(tmp)
            if os.path.exists(snap["db_copy"]):
                shutil.copy2(snap["db_copy"], tmp)
            else:  # a cópia sumiu: tira do zip de segurança
                with zipfile.ZipFile(os.path.join(config.BACKUPS_DIR, snap["zip"])) as z, z.open("starflix.db") as f, open(tmp, "wb") as out:
                    shutil.copyfileobj(f, out)
            for suf in ("-wal", "-shm"):
                _rm(config.DB_PATH + suf)
            os.replace(tmp, config.DB_PATH)
            for suf in ("-wal", "-shm"):  # só existem se a cópia foi bruta (banco atual danificado)
                if os.path.exists(snap["db_copy"] + suf):
                    shutil.copy2(snap["db_copy"] + suf, config.DB_PATH + suf)
            if not _db_ok(config.DB_PATH) and not os.path.exists(snap["db_copy"] + "-wal"):
                raise RuntimeError("o banco revertido não passou na verificação")
    old_av = config.AVATARS_DIR + ".antes-restore"
    if st["av_placed"] or st["av_moved"]:
        if st["av_placed"]:
            _rm(config.AVATARS_DIR)
        if st["av_moved"]:
            os.replace(old_av, config.AVATARS_DIR)


def restore(src, info=None):
    """Troca o banco e as fotos pelos do zip. Ordem: valida o zip → backup de segurança do estado atual → prepara tudo ao lado (sem tocar no atual)
    → troca → confere o resultado. Se QUALQUER passo depois do backup falhar, volta ao estado de antes (reversão automática).
    Devolve quantas fotos voltaram; `info` (dict, opcional) recebe {"pre_backup": nome do zip de segurança}. Levanta RestoreError."""
    names = validate(src)
    new_avatars = [n for n in names if n != "starflix.db"]
    snap = snapshot()  # falhou? levanta RestoreError e nada foi alterado
    if info is not None:
        info["pre_backup"] = snap["zip"] if snap else None
    tmp_db = config.DB_PATH + ".restore"
    stage_av = config.AVATARS_DIR + ".novo"
    old_av = config.AVATARS_DIR + ".antes-restore"
    st = {"db": False, "av_moved": False, "av_placed": False}
    try:
        _rm(tmp_db)
        _rm(stage_av)
        os.makedirs(stage_av)
        with zipfile.ZipFile(src) as z:  # 1) tudo preparado ao lado: o banco e as fotos atuais seguem intactos
            with z.open("starflix.db") as f, open(tmp_db, "wb") as out:
                shutil.copyfileobj(f, out)
            for n in new_avatars:
                with z.open(n) as f, open(os.path.join(stage_av, os.path.basename(n)), "wb") as out:
                    shutil.copyfileobj(f, out)
        if not _db_ok(tmp_db):
            raise RuntimeError("o banco extraído não passou na verificação")
        # 2) troca
        st["db"] = True  # a partir daqui o banco atual pode ter mudado
        for suf in ("-wal", "-shm"):
            _rm(config.DB_PATH + suf)
        os.replace(tmp_db, config.DB_PATH)
        if os.path.isdir(config.AVATARS_DIR):
            _rm(old_av)
            os.replace(config.AVATARS_DIR, old_av)
            st["av_moved"] = True
        st["av_placed"] = True
        os.replace(stage_av, config.AVATARS_DIR)
        # 3) confere o que ficou no lugar
        if not _db_ok(config.DB_PATH):
            raise RuntimeError("o banco restaurado não passou na verificação")
    except Exception as e:
        try:
            _rollback(snap, st)
        except Exception as e2:
            raise RestoreError(f"restauração falhou ({e}) e a reversão também ({e2}). Restaure o backup de segurança {snap['zip'] if snap else '?'}",
                               "err.restore_revert_falhou", zip=snap["zip"] if snap else "?")
        raise RestoreError(f"a restauração falhou ({e}); o estado anterior foi recuperado", "err.restore_revertido")
    finally:
        _rm(tmp_db)
        _rm(stage_av)
    return len(new_avatars)


RESULT = os.path.join(os.path.dirname(config.DB_PATH), "restore-result.json")


def exec_server():
    """60.10: devolve o processo ao servidor (mesmos argumentos com que ele foi iniciado; sem eles, run.py)."""
    try:
        argv = json.loads(os.environ.pop("STARFLIX_BOOT_ARGV", ""))
        if not isinstance(argv, list) or not argv:
            raise ValueError
    except ValueError:
        argv = [os.path.join(ROOT, "run.py")]
    os.chdir(ROOT)
    os.execv(sys.executable, [sys.executable] + argv)


def serve_mode(src):
    """Modo do botão Restaurar: restaura e volta a ser o servidor, qualquer que seja o resultado."""
    res = {"ok": True, "name": os.path.basename(src), "at": int(time.time())}
    info = {}
    try:
        res["photos"] = restore(src, info)
        res["pre_backup"] = info.get("pre_backup")
    except RestoreError as e:
        res.update(ok=False, key=e.key, vars=e.vars, msg=e.msg)
    except Exception as e:  # disco cheio, permissão...: o servidor sobe mesmo assim e o site mostra o erro
        res.update(ok=False, key="err.restore_falhou", vars={}, msg=str(e))
    try:
        with open(RESULT, "w", encoding="utf-8") as f:
            json.dump(res, f)
    except OSError:
        pass
    exec_server()


def main(argv):
    force = "--force" in argv
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        die("uso: python3 scripts/restore_backup.py <arquivo.zip> [--force]")
    src = args[0]
    if "--exec-server" in argv:
        serve_mode(src)
        return
    try:
        validate(src)
        if not force and server_running():
            die(f"o servidor parece estar ligado (porta {server_port()} responde). Pare com: sudo systemctl stop starflix")
        info = {}
        n = restore(src, info)
    except RestoreError as e:
        die(e.msg)
    print(f"Restaurado: banco e {n} foto(s) de perfil.")
    if info.get("pre_backup"):
        print("Backup de segurança do estado anterior:", os.path.join(config.BACKUPS_DIR, info["pre_backup"]))
    print("O banco anterior ficou em", config.DB_PATH + ".antes-restore")
    print("Agora suba o servidor: sudo systemctl start starflix")


if __name__ == "__main__":
    main(sys.argv[1:])
