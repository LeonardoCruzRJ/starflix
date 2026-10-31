import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_PORT = 32000
PORT = DEFAULT_PORT  # 60.1: porta de escuta; run.py a troca pela salva em Configurações → Servidor (settings.server_port)
DISCOVERY_PORT = 32010  # 62.2: UDP; responde ao broadcast "STARFLIX_DISCOVER" (apps sem mDNS, como o da Roku)
RESTART_ON_PORT = False  # 60.1: run.py liga quando roda como servidor; a troca de porta reinicia o processo só se for True
VERSION = "1.0.718"  # 58.2: sobe a cada entrega (igual ao versionName do app); aparece em /api/server-info
CORS_ORIGINS = [o.strip().rstrip("/") for o in os.environ.get("STARFLIX_CORS_ORIGINS", "https://roku.casaleoweb.com.br").split(",") if o.strip()]  # 62.14: origens de páginas que podem chamar a API (emulador Roku no navegador); "*" libera qualquer uma; vazio desliga
MAX_TRANSCODES = int(os.environ.get("STARFLIX_MAX_TRANSCODES", 3))  # ffmpeg simultâneos (0 = sem limite)
MIN_FREE_GB = float(os.environ.get("STARFLIX_MIN_FREE_GB", 5))  # espaço livre mínimo em data/transcode (0 = sem limite)
THREADS = int(os.environ.get("STARFLIX_THREADS", 64))
DATA_DIR = os.path.abspath(os.environ.get("STARFLIX_DATA", os.path.join(BASE_DIR, "data")))

DB_PATH = os.path.join(DATA_DIR, "starflix.db")
POSTERS_DIR = os.path.join(DATA_DIR, "posters")
TRANSCODE_DIR = os.path.join(DATA_DIR, "transcode")
SUBS_DIR = os.path.join(DATA_DIR, "subs")
AVATARS_DIR = os.path.join(DATA_DIR, "avatars")
BACKUPS_DIR = os.path.join(DATA_DIR, "backups")  # 51.1
OPTIMIZED_DIR = os.path.join(DATA_DIR, "optimized")  # 52.7: <tipo>/<id>.mp4

# 45.5: as chaves de API ficam no banco (Configurações -> Agentes); server/agents.py as carrega aqui na partida e ao salvar
TMDB_API_KEY = ""
TVDB_API_KEY = ""
OMDB_API_KEY = ""  # opcional (23.31): notas IMDb/Rotten Tomatoes
SUBDL_API_KEY = ""  # 46.1: legendas (server/subdl.py)

# segundos entre varreduras automáticas (0 desativa)
SCAN_INTERVAL = int(os.environ.get("STARFLIX_SCAN_INTERVAL", 3600))
# 45.7: idiomas também no banco (Configurações -> Agentes); server/agents.py os carrega aqui. A região do TMDB acompanha o idioma (pt-BR -> BR)
TMDB_LANG = "pt-BR"
TMDB_REGION = "BR"  # 32.2: país das listas do TMDB (Início)
TVDB_LANG = "por"
SUBDL_LANG = "BR_PT"  # 46.1: idioma das legendas baixadas do SubDL
TMDB_IMG_SIZE = os.environ.get("TMDB_IMG_SIZE", "w500")

# limpeza de sessões de transcode: segundos sem atividade até apagar / intervalo da varredura (0 desativa)
TRANSCODE_TTL = int(os.environ.get("STARFLIX_TRANSCODE_TTL", 600))
TRANSCODE_CLEAN_INTERVAL = int(os.environ.get("STARFLIX_TRANSCODE_CLEAN_INTERVAL", 60))
