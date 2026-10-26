CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    full_name TEXT,                              -- 26.1: perfil/conta
    avatar TEXT,                                 -- arquivo em data/avatars/
    location TEXT,
    bio TEXT,
    link TEXT,
    show_badge INTEGER NOT NULL DEFAULT 1,       -- mostrar "Entrou <ano>"
    prefs TEXT,                                  -- JSON: idioma, áudio/legenda, indicadores de assistidos, avaliações
    session_ver INTEGER NOT NULL DEFAULT 0       -- incrementa para encerrar as outras sessões
);

CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    avatar TEXT
);

CREATE TABLE IF NOT EXISTS libraries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('movie', 'show', 'video')),
    path TEXT NOT NULL,   -- primeira pasta (compatibilidade); todas ficam em library_folders
    lang TEXT,            -- idioma dos metadados (ex.: pt-BR); NULL = idioma do servidor (TMDB_LANG)
    prefs TEXT,           -- JSON: agent, visibility, cert_country, original_titles, lang_art, local_art, adult, rating_source, collection_mode
    scanned_at INTEGER    -- 29.1: epoch do último exame concluído ("Última atualização há …")
);

-- pastas de cada biblioteca (28.1); ord 0 = libraries.path
CREATE TABLE IF NOT EXISTS library_folders (
    library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    ord INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (library_id, path)
);
CREATE INDEX IF NOT EXISTS idx_library_folders_library ON library_folders(library_id);

-- 29.1: bibliotecas desafixadas da barra lateral por usuário (sem linha = fixada)
CREATE TABLE IF NOT EXISTS library_unpinned (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, library_id)
);

-- 45.3: ordem da barra lateral por usuário (arrastar na web); sem linha = depois das ordenadas, por nome
CREATE TABLE IF NOT EXISTS library_order (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    PRIMARY KEY (user_id, library_id)
);

-- configurações gerais do servidor (28.1): chave/valor (ex.: merge_recent = '1')
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- filmes e séries (série não tem arquivo; episódios ficam em episodes)
CREATE TABLE IF NOT EXISTS media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    year INTEGER,
    overview TEXT,
    genres TEXT,
    poster TEXT,
    tmdb_id INTEGER,
    tvdb_id INTEGER,
    path TEXT,
    info TEXT,
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- 23.12: metadados estendidos (instalações antigas ganham estas colunas por migração em db.init_db)
    original_title TEXT,
    sort_title TEXT,
    release_date TEXT,
    content_rating TEXT,
    rating REAL,
    tagline TEXT,
    backdrop TEXT,
    logo TEXT,
    square TEXT,
    locks TEXT,   -- JSON {"title": 1, ...}: campo travado nunca é sobrescrito por scan/TMDB
    prefs TEXT,   -- JSON: áudio/legenda/idioma/título original preferidos
    meta_ok INTEGER,  -- 1 = metadados estendidos (23.13/23.17) já gravados
    imdb_id TEXT,     -- 23.31: id IMDb (TMDB external_ids)
    imdb_rating REAL, -- 23.31: nota IMDb (OMDb, opcional)
    rt_rating INTEGER -- 23.31: Rotten Tomatoes em % (OMDb, opcional)
);

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    season INTEGER NOT NULL,
    episode INTEGER NOT NULL,
    title TEXT,
    overview TEXT,
    path TEXT NOT NULL,
    info TEXT,
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    still TEXT,
    air_date TEXT,
    content_rating TEXT,
    rating REAL,
    sort_title TEXT,
    locks TEXT,
    imdb_rating REAL,   -- 36.1: nota IMDb do episódio (OMDb)
    crew_ok INTEGER     -- 36.1: 1 = diretor/roteirista do episódio já buscados (TMDB)
);

CREATE TABLE IF NOT EXISTS progress (
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    item_type TEXT NOT NULL CHECK (item_type IN ('movie', 'episode')),
    item_id INTEGER NOT NULL,
    position REAL NOT NULL DEFAULT 0,
    watched INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (profile_id, item_type, item_id)
);

CREATE TABLE IF NOT EXISTS user_libraries (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, library_id)
);

CREATE INDEX IF NOT EXISTS idx_media_library ON media(library_id);
CREATE INDEX IF NOT EXISTS idx_episodes_media ON episodes(media_id);
CREATE INDEX IF NOT EXISTS idx_user_libraries_library ON user_libraries(library_id);
CREATE INDEX IF NOT EXISTS idx_profiles_user ON profiles(user_id);

-- 23.12: tabelas novas da reformulação da interface
CREATE TABLE IF NOT EXISTS seasons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    season INTEGER NOT NULL,
    title TEXT,
    overview TEXT,
    poster TEXT,
    backdrop TEXT,
    locks TEXT,
    prefs TEXT,
    UNIQUE (media_id, season)
);

CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    photo TEXT,
    tmdb_id INTEGER UNIQUE,
    birthday TEXT, deathday TEXT, bio TEXT, dept TEXT, imdb_id TEXT, instagram TEXT, twitter TEXT,
    photo_big TEXT, filmography TEXT, info_ok INTEGER, info_at INTEGER, bio_lang TEXT
);

CREATE TABLE IF NOT EXISTS credits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    episode_id INTEGER REFERENCES episodes(id) ON DELETE CASCADE,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('cast', 'director', 'writer', 'producer')),
    character TEXT,
    ord INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('genre', 'country', 'label')),
    name TEXT NOT NULL,
    UNIQUE (media_id, kind, name)
);

CREATE TABLE IF NOT EXISTS my_list (
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (profile_id, media_id)
);

CREATE TABLE IF NOT EXISTS stars (
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    item_type TEXT NOT NULL CHECK (item_type IN ('movie', 'show', 'season', 'episode', 'collection')),
    item_id INTEGER NOT NULL,
    stars INTEGER NOT NULL CHECK (stars BETWEEN 0 AND 10),  -- meia estrela = 1
    PRIMARY KEY (profile_id, item_type, item_id)
);

-- 23.17: recomendações do TMDB (só entram na tela as que existem na biblioteca)
CREATE TABLE IF NOT EXISTS related (
    media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    tmdb_id INTEGER NOT NULL,
    ord INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (media_id, tmdb_id)
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    author TEXT,
    avatar TEXT,
    rating REAL,
    created TEXT,
    text TEXT
);

CREATE INDEX IF NOT EXISTS idx_seasons_media ON seasons(media_id);
CREATE INDEX IF NOT EXISTS idx_credits_media ON credits(media_id);
CREATE INDEX IF NOT EXISTS idx_credits_episode ON credits(episode_id);
CREATE INDEX IF NOT EXISTS idx_credits_person ON credits(person_id);
CREATE INDEX IF NOT EXISTS idx_tags_media ON tags(media_id);
CREATE INDEX IF NOT EXISTS idx_my_list_media ON my_list(media_id);
CREATE INDEX IF NOT EXISTS idx_reviews_media ON reviews(media_id);

-- 24.1: coleções manuais (criadas pelo admin; uma biblioteca por coleção)
CREATE TABLE IF NOT EXISTS collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    sort_title TEXT,
    summary TEXT,
    content_rating TEXT,
    poster TEXT,     -- caminho relativo a data/posters (col/...) ou vazio (fallback: pôster do primeiro item)
    backdrop TEXT,
    logo TEXT,
    square TEXT,
    labels TEXT,     -- JSON: lista de rótulos livres
    prefs TEXT,      -- JSON: {"mode": "default|hide|both"}
    locks TEXT,      -- JSON {"title": 1, ...}
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    smart INTEGER NOT NULL DEFAULT 0,  -- 31.1: coleção inteligente (itens calculados pelas regras)
    rules TEXT,                        -- JSON {"match": "all|any", "rules": [{field, op, value}]}
    limit_n INTEGER                    -- LIMITAR A (NULL = sem limite)
);

CREATE TABLE IF NOT EXISTS collection_items (
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (collection_id, media_id)
);

CREATE INDEX IF NOT EXISTS idx_collections_library ON collections(library_id);
CREATE INDEX IF NOT EXISTS idx_collection_items_media ON collection_items(media_id);

-- 31.1: listas de reprodução (por usuário; inteligente = itens calculados pelas regras)
CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    smart INTEGER NOT NULL DEFAULT 0,
    rules TEXT,
    limit_n INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS playlist_items (
    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    ord INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (playlist_id, media_id)
);

CREATE INDEX IF NOT EXISTS idx_playlists_user ON playlists(user_id, library_id);
CREATE INDEX IF NOT EXISTS idx_playlist_items_media ON playlist_items(media_id);

-- 32.1: listas do TMDB (ids por lista/região/idioma; renovadas a cada 24 h) e preferências do Início por perfil
CREATE TABLE IF NOT EXISTS tmdb_lists (
    list_key TEXT NOT NULL,
    region TEXT NOT NULL DEFAULT '',
    lang TEXT NOT NULL DEFAULT '',
    ids TEXT NOT NULL DEFAULT '[]',  -- JSON de tmdb_id
    fetched_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (list_key, region, lang)
);

CREATE TABLE IF NOT EXISTS home_prefs (
    profile_id INTEGER PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
    hidden TEXT NOT NULL DEFAULT '[]',  -- JSON de keys ocultas
    "order" TEXT NOT NULL DEFAULT '[]'  -- JSON de keys na ordem escolhida; vazio = padrão
);

-- 35.3: arquivos repetidos de um filme/episódio já existente (o scanner não os adiciona de novo); somem junto com o item
CREATE TABLE IF NOT EXISTS media_dups (
    path TEXT PRIMARY KEY,
    media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_media_dups_media ON media_dups(media_id);

-- 38.3: ordenação e filtros da biblioteca por perfil e biblioteca (antes ficavam num cookie do navegador)
CREATE TABLE IF NOT EXISTS library_view_prefs (
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    sort TEXT NOT NULL DEFAULT 'title',
    dir TEXT,
    filter TEXT NOT NULL DEFAULT 'all',
    genre TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (profile_id, library_id)
);

-- 40.1: pareamento da TV (Fase 40). A TV pede um código de 6 caracteres; `user_id` só é preenchido quando o usuário autoriza em /tv.
-- O token nasce na 1ª consulta da TV depois da autorização (aí o código vira `used`), então nunca fica guardado em texto puro.
CREATE TABLE IF NOT EXISTS tv_codes (
    code TEXT PRIMARY KEY,
    poll TEXT NOT NULL UNIQUE,
    device_name TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    used INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tv_codes_expires ON tv_codes(expires_at);

-- TVs autorizadas: um token por aparelho (guardado só como hash), apagado junto com o usuário
CREATE TABLE IF NOT EXISTS tv_devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL DEFAULT '',
    token_hash TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    last_seen INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tv_devices_user ON tv_devices(user_id);

-- 58.4: conexão do celular (Fase 58). `phone_tokens` = QR (60 s) e link (24 h) de uso único gerados no site; só o hash fica guardado.
CREATE TABLE IF NOT EXISTS phone_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'qr',
    token_hash TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    used_at INTEGER,
    device_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_phone_tokens_expires ON phone_tokens(expires_at);

-- celulares autorizados: um token por aparelho (só o hash), apagado junto com o usuário
CREATE TABLE IF NOT EXISTS phone_devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL DEFAULT '',
    token_hash TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    last_seen INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_phone_devices_user ON phone_devices(user_id);

-- 58.4: ticket de 5 min que o celular entrega à TV (uso único; só o hash)
CREATE TABLE IF NOT EXISTS tv_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    used_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_tv_tickets_expires ON tv_tickets(expires_at);

-- 46.1: tentativas de baixar legenda do SubDL por arquivo de vídeo e tipo (full|forced); status ok|none.
-- Exame automático só tenta o que nunca foi tentado; "Examinar arquivos" tenta de novo o que ainda falta, uma vez por exame.
CREATE TABLE IF NOT EXISTS subtitle_fetch (
    path TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    at INTEGER NOT NULL,
    PRIMARY KEY (path, kind)
);

-- 48.5: temporadas já varridas pela detecção automática (refaz só quando muda o número de arquivos)
CREATE TABLE IF NOT EXISTS marker_scan (
    media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    season INTEGER NOT NULL,
    n INTEGER NOT NULL,
    PRIMARY KEY (media_id, season)
);

-- 48.1: marcadores de abertura/créditos por episódio (source: manual | chapter | auto)
CREATE TABLE IF NOT EXISTS episode_markers (
    episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('intro', 'credits')),
    start REAL NOT NULL,
    end REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    confidence REAL NOT NULL DEFAULT 1,
    PRIMARY KEY (episode_id, kind)
);

-- 47.1: atraso da legenda (s) por vídeo e legenda; vale para todos os perfis. sub_key = ext:<arquivo> | emb:<índice da faixa>
CREATE TABLE IF NOT EXISTS sub_offset (
    item_type TEXT NOT NULL,
    item_id INTEGER NOT NULL,
    sub_key TEXT NOT NULL,
    offset REAL NOT NULL,
    PRIMARY KEY (item_type, item_id, sub_key)
);

-- 52.6: aparelhos que já tocaram (navegador por usuário e agente, TV por tv_devices.id) com o último `caps`; `required` = precisa tocar sem transcode
CREATE TABLE IF NOT EXISTS client_caps (
    client_key TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    label TEXT NOT NULL DEFAULT '',
    caps TEXT NOT NULL DEFAULT '',
    required INTEGER NOT NULL DEFAULT 0,
    last_seen INTEGER NOT NULL DEFAULT 0
);

-- 52.6: versões otimizadas (52.7 em diante); status ok|fail|skip
CREATE TABLE IF NOT EXISTS optimized (
    item_type TEXT NOT NULL,
    item_id INTEGER NOT NULL,
    path TEXT NOT NULL DEFAULT '',
    src_size INTEGER NOT NULL DEFAULT 0,
    src_mtime REAL NOT NULL DEFAULT 0,
    out_path TEXT NOT NULL DEFAULT '',
    out_size INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'fail',
    reason TEXT NOT NULL DEFAULT '',
    tries INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (item_type, item_id)
);

-- 59.41: metadados já buscados em cada idioma (reaproveitados quando o usuário volta a ele); kind = media | season | episode
CREATE TABLE IF NOT EXISTS meta_cache (
    lang TEXT NOT NULL,
    kind TEXT NOT NULL,
    ref INTEGER NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (lang, kind, ref)
);
