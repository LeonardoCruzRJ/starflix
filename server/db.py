import json
import os
import sqlite3
import time
import unicodedata

import config

SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


def fold(text):
    """Minúsculas e sem acentos (LIKE e COLLATE NOCASE do SQLite só tratam ASCII); usada em busca e ordenação."""
    t = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in t if not unicodedata.combining(c)).casefold()


class _Conn(sqlite3.Connection):
    """`with get_db() as conn:` faz commit/rollback E fecha a conexão (o padrão do sqlite3 só faz commit)."""

    def __exit__(self, *exc):
        try:
            return super().__exit__(*exc)
        finally:
            self.close()


def get_db():
    conn = sqlite3.connect(config.DB_PATH, timeout=30, factory=_Conn)
    conn.row_factory = sqlite3.Row
    conn.create_function("fold", 1, fold, deterministic=True)
    conn.create_function("dtitle", 3, display_title)  # 28.5: título original quando a biblioteca pede
    conn.create_function("casefold", 1, lambda t: (t or "").casefold(), deterministic=True)  # lower() do SQLite só trata ASCII
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


# 23.12: colunas adicionadas a tabelas que já existem em instalações antigas (só ADD COLUMN, nunca apaga dados)
NEW_COLUMNS = {
    "profiles": [("photo", "TEXT"), ("prefs", "TEXT")],  # 44.1: foto e preferências individuais de cada perfil
    "libraries": [("lang", "TEXT"), ("prefs", "TEXT"), ("scanned_at", "INTEGER")],  # 28.1, 29.1
    "users": [  # 26.1
        ("full_name", "TEXT"), ("avatar", "TEXT"), ("location", "TEXT"), ("bio", "TEXT"), ("link", "TEXT"),
        ("show_badge", "INTEGER NOT NULL DEFAULT 1"), ("prefs", "TEXT"), ("session_ver", "INTEGER NOT NULL DEFAULT 0"),
    ],
    "media": [
        ("original_title", "TEXT"), ("sort_title", "TEXT"), ("release_date", "TEXT"), ("content_rating", "TEXT"),
        ("rating", "REAL"), ("tagline", "TEXT"), ("backdrop", "TEXT"), ("logo", "TEXT"), ("square", "TEXT"),
        ("locks", "TEXT"), ("prefs", "TEXT"), ("meta_ok", "INTEGER"),
        ("imdb_id", "TEXT"), ("imdb_rating", "REAL"), ("rt_rating", "INTEGER"),
    ],
    "collections": [("smart", "INTEGER NOT NULL DEFAULT 0"), ("rules", "TEXT"), ("limit_n", "INTEGER")],  # 31.1
    "playlists": [("summary", "TEXT"), ("poster", "TEXT"), ("backdrop", "TEXT"), ("logo", "TEXT"), ("square", "TEXT")],  # 31.9
    "people": [  # 37.1: página da pessoa (dados do TMDB, buscados na 1ª visita)
        ("birthday", "TEXT"), ("deathday", "TEXT"), ("bio", "TEXT"), ("dept", "TEXT"), ("imdb_id", "TEXT"),
        ("instagram", "TEXT"), ("twitter", "TEXT"), ("photo_big", "TEXT"), ("filmography", "TEXT"),
        ("info_ok", "INTEGER"), ("info_at", "INTEGER"),
        ("bio_lang", "TEXT"),  # 57.5: idioma da biografia gravada (pt, en…)
    ],
    "episodes": [
        ("still", "TEXT"), ("air_date", "TEXT"), ("content_rating", "TEXT"), ("rating", "REAL"),
        ("sort_title", "TEXT"), ("locks", "TEXT"),
        ("imdb_rating", "REAL"), ("crew_ok", "INTEGER"),  # 36.1: nota IMDb (OMDb) e diretor/roteirista (TMDB) do episódio
    ],
}


def migrate(conn):
    """Migração idempotente: confere `PRAGMA table_info` e faz `ALTER TABLE ADD COLUMN` do que faltar."""
    for table, cols in NEW_COLUMNS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols:
            if name in have:
                continue
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                if (table, name) == ("media", "imdb_id"):  # 23.31: refaz os metadados uma vez para trazer o id IMDb
                    conn.execute("UPDATE media SET meta_ok = NULL WHERE tmdb_id > 0")
                if (table, name) == ("people", "bio_lang"):  # 57.5: refaz uma vez as biografias já gravadas (estavam em inglês)
                    conn.execute("UPDATE people SET info_ok = 0, info_at = 0 WHERE tmdb_id IS NOT NULL AND bio IS NOT NULL")
            except sqlite3.OperationalError as e:  # outro processo adicionou entre a checagem e o ALTER
                if "duplicate column" not in str(e).lower():
                    raise
    # 28.1: toda biblioteca existente ganha sua pasta atual em library_folders (idempotente)
    conn.execute(
        "INSERT OR IGNORE INTO library_folders (library_id, path, ord) "
        "SELECT id, path, 0 FROM libraries WHERE id NOT IN (SELECT library_id FROM library_folders)"
    )


def clean_tv_codes(conn, now=None, keep=3600):
    """40.1: apaga os códigos de pareamento da TV vencidos há mais de `keep` s (até lá ficam para a TV ver `expired`). Devolve quantos apagou."""
    import time
    limit = (time.time() if now is None else now) - keep
    n = conn.execute("DELETE FROM tv_codes WHERE expires_at < ?", (limit,)).rowcount
    # 58.4: tokens de QR/link do celular e tickets da TV vencidos saem junto
    n += conn.execute("DELETE FROM phone_tokens WHERE expires_at < ?", (limit,)).rowcount
    n += conn.execute("DELETE FROM tv_tickets WHERE expires_at < ?", (limit,)).rowcount
    return n


def hdr_label(info):
    """Selo de tela: \"DV\" (Dolby Vision), \"HDR\" (HDR10/HLG) ou None."""
    h = ((info or {}).get("video") or {}).get("hdr")
    return "DV" if h in ("dv5", "dv8") else "HDR" if h in ("hdr10", "hlg") else None


PREF_DEFAULTS = {"agent": "tmdb", "visibility": "all", "cert_country": "BR", "original_titles": False, "lang_art": True,
                 "local_art": True, "adult": False, "detect_markers": True, "rating_source": "tmdb", "collection_mode": "default", "thumbs": True, "trickplay": False}


def lib_prefs(row):
    """Opções da biblioteca (libraries.prefs) com os padrões aplicados."""
    try:
        saved = json.loads(row["prefs"]) if row["prefs"] else {}
    except ValueError:
        saved = {}
    return {k: saved.get(k, v) for k, v in PREF_DEFAULTS.items()}


_orig_cache = {"t": 0.0, "ids": frozenset()}


def invalidate_lib_prefs():
    """Chamar ao criar/editar biblioteca: força reler quais bibliotecas usam títulos originais."""
    _orig_cache["t"] = 0.0


def _orig_libs():
    if time.monotonic() - _orig_cache["t"] > 30:
        try:
            c = sqlite3.connect(config.DB_PATH, timeout=30)
            try:
                rows = c.execute("SELECT id, prefs FROM libraries").fetchall()
            finally:
                c.close()
        except sqlite3.Error:
            return _orig_cache["ids"]
        ids = set()
        for i, p in rows:
            try:
                if p and json.loads(p).get("original_titles") is True:
                    ids.add(i)
            except (ValueError, AttributeError):
                pass
        _orig_cache["ids"], _orig_cache["t"] = frozenset(ids), time.monotonic()
    return _orig_cache["ids"]


def display_title(library_id, title, original):
    """28.5: título exibido (original_title se a biblioteca usa títulos originais e ele existir)."""
    return original if original and library_id in _orig_libs() else title


def library_folders(conn, lid):
    """Pastas da biblioteca em ordem (a primeira = libraries.path); sem linhas, cai no libraries.path."""
    rows = [r["path"] for r in conn.execute("SELECT path FROM library_folders WHERE library_id = ? ORDER BY ord, path", (lid,))]
    if rows:
        return rows
    r = conn.execute("SELECT path FROM libraries WHERE id = ?", (lid,)).fetchone()
    return [r["path"]] if r else []


def set_primary_folder(conn, lid, path):
    """Mantém library_folders (ord 0) igual a libraries.path enquanto as rotas antigas de formulário existirem."""
    cur = conn.execute("UPDATE library_folders SET path = ? WHERE library_id = ? AND ord = 0", (path, lid))
    if not cur.rowcount:
        conn.execute("INSERT OR IGNORE INTO library_folders (library_id, path, ord) VALUES (?, ?, 0)", (lid, path))


_STARS_SQL = """CREATE TABLE stars (
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    item_type TEXT NOT NULL CHECK (item_type IN ('movie', 'show', 'season', 'episode', 'collection')),
    item_id INTEGER NOT NULL,
    stars INTEGER NOT NULL CHECK (stars BETWEEN 0 AND 10),  -- meia estrela = 1
    PRIMARY KEY (profile_id, item_type, item_id)
)"""


def _migrate_stars(conn):
    """24.1: instalações antigas têm CHECK sem 'collection' em stars; recria a tabela (copiando os dados) uma única vez."""
    r = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'stars'").fetchone()
    if not r or "'collection'" in (r["sql"] or ""):
        return
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DROP TABLE IF EXISTS stars_old")
        conn.execute("ALTER TABLE stars RENAME TO stars_old")
        conn.execute(_STARS_SQL)
        conn.execute("INSERT INTO stars (profile_id, item_type, item_id, stars) SELECT profile_id, item_type, item_id, stars FROM stars_old")
        conn.execute("DROP TABLE stars_old")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


_LIBS_SQL = """CREATE TABLE libraries_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('movie', 'show', 'video')),
    path TEXT NOT NULL,
    lang TEXT,
    prefs TEXT,
    scanned_at INTEGER
)"""


def _migrate_libraries_video(conn):
    """34.1: instalações antigas têm CHECK sem 'video' em libraries; recria a tabela (copiando os dados) uma única vez.
    Sem foreign_keys durante a troca, senão o DROP apagaria em cascata tudo que aponta para a biblioteca."""
    r = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'libraries'").fetchone()
    if not r or "'video'" in (r["sql"] or ""):
        return
    if conn.in_transaction:
        conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        seq = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'libraries'").fetchone()
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DROP TABLE IF EXISTS libraries_new")
            conn.execute(_LIBS_SQL)
            conn.execute("INSERT INTO libraries_new (id, name, type, path, lang, prefs, scanned_at) "
                         "SELECT id, name, type, path, lang, prefs, scanned_at FROM libraries")
            conn.execute("DROP TABLE libraries")
            conn.execute("ALTER TABLE libraries_new RENAME TO libraries")
            if seq:
                conn.execute("UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = 'libraries'", (seq["seq"],))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def init_db():
    for d in (config.DATA_DIR, config.POSTERS_DIR, config.TRANSCODE_DIR, config.SUBS_DIR, config.AVATARS_DIR, config.BACKUPS_DIR):
        os.makedirs(d, exist_ok=True)
    with get_db() as conn, open(SCHEMA, encoding="utf-8") as f:
        conn.execute("PRAGMA journal_mode = WAL")  # persiste no arquivo; leitores não bloqueiam o escritor
        conn.executescript(f.read())
        migrate(conn)
        _migrate_stars(conn)
        _migrate_libraries_video(conn)


def prune_stars(conn):
    """Apaga estrelas (e o atraso de legenda, 47.1) de itens que não existem mais (item_id é polimórfico, sem FK)."""
    for kind, table in (("movie", "media"), ("show", "media"), ("season", "seasons"), ("episode", "episodes"), ("collection", "collections")):
        conn.execute(f"DELETE FROM stars WHERE item_type = ? AND item_id NOT IN (SELECT id FROM {table})", (kind,))
    conn.execute("DELETE FROM episode_markers WHERE episode_id NOT IN (SELECT id FROM episodes)")  # 48.1
    for kind, table in (("movie", "media"), ("episode", "episodes")):
        conn.execute(f"DELETE FROM sub_offset WHERE item_type = ? AND item_id NOT IN (SELECT id FROM {table})", (kind,))
