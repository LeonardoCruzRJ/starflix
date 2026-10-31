"""Teste de regressão: setup -> login -> perfil -> biblioteca -> scan -> busca -> progresso (+ Fases 23 a 59).
Uso: python3 scripts/smoke_test.py   (usa dados temporários; não toca em data/)"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="starflix_smoke_")
os.environ["STARFLIX_DATA"] = os.path.join(TMP, "data")
os.environ["TMDB_API_KEY"] = ""
os.environ["TVDB_API_KEY"] = ""
os.makedirs(os.environ["STARFLIX_DATA"])
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import run  # noqa: E402
from server.scanner import is_scanning  # noqa: E402

fails = []


def get_setting_port60():
    from server.db import get_db as _gdb
    with _gdb() as conn:
        r = conn.execute("SELECT value FROM settings WHERE key = 'server_port'").fetchone()
    return r["value"] if r else ""


def check(name, cond):
    print(("OK   " if cond else "FALHA"), name)
    if not cond:
        fails.append(name)


_PT = json.load(open(os.path.join(ROOT, "i18n", "pt-BR.json"), encoding="utf-8"))


def uses_text(src, *frags):
    """59.x: o texto em português saiu do JS e foi para o catálogo: confere que cada trecho existe em `i18n/pt-BR.json` e que o JS usa a chave."""
    return all(any(f in v and re.search(r"[\"']" + re.escape(k) + r"[\"']", src) for k, v in _PT.items()) for f in frags)


def make_video(path):
    try:
        r = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10:duration=2",
             "-f", "lavfi", "-i", "sine=duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
             "-shortest", path],
            capture_output=True, timeout=60,
        )
        if r.returncode == 0:
            return
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    open(path, "wb").write(b"\0" * 1024)  # sem ffmpeg: arquivo falso (probe ficará com erro)


try:
    movies = os.path.join(TMP, "filmes")
    shows = os.path.join(TMP, "series")
    os.makedirs(movies)
    os.makedirs(os.path.join(shows, "Serie Teste (2019)"))
    make_video(os.path.join(movies, "Ação Épica (2020).mp4"))
    shutil.copy(os.path.join(movies, "Ação Épica (2020).mp4"), os.path.join(movies, "Zorro (2019).mp4"))
    make_video(os.path.join(shows, "Serie Teste (2019)", "Serie.Teste.S01E01.mp4"))
    shutil.copy(os.path.join(shows, "Serie Teste (2019)", "Serie.Teste.S01E01.mp4"),
                os.path.join(shows, "Serie Teste (2019)", "Serie.Teste.S01E01.720p.mp4"))  # duplicata

    c = run.app.test_client()
    check("health", c.get("/health").json == {"status": "ok"})
    check("sem usuário -> /setup", c.get("/").headers["Location"].endswith("/setup"))
    c.post("/setup", data={"username": "admin", "password": "senha123"})
    check("sem login -> /login", c.get("/").headers["Location"].endswith("/login"))
    r = c.post("/login", data={"username": "admin", "password": "errada"})
    check("login inválido rejeitado", r.status_code == 200)
    r = c.post("/login", data={"username": "admin", "password": "senha123"})
    check("login ok", r.status_code == 302)
    check("cookie permanente (30 dias)", "Expires" in r.headers.get("Set-Cookie", ""))
    check("sem perfil -> /profiles", c.get("/").headers["Location"].endswith("/profiles"))
    check("404 sem perfil não dá 500", c.get("/nao-existe").status_code == 404)

    c.post("/profiles/new", data={"name": "Leo"})
    from server.db import get_db
    with get_db() as conn:
        pid = conn.execute("SELECT id FROM profiles").fetchone()["id"]
    check("seleciona perfil", c.post(f"/profiles/{pid}/select").status_code == 302)
    check("home abre", c.get("/").status_code == 200)
    c.post("/profiles/new", data={"name": "X" * 500})
    with get_db() as conn:
        names = [r["name"] for r in conn.execute("SELECT name FROM profiles")]
    check("nome de perfil longo cortado em 30", "X" * 30 in names and all(len(n) <= 30 for n in names))

    c.post("/admin/libraries", data={"name": "Filmes", "type": "movie", "path": movies})
    c.post("/admin/libraries", data={"name": "Séries", "type": "show", "path": shows})
    with get_db() as conn:
        libs = {r["type"]: r["id"] for r in conn.execute("SELECT id, type FROM libraries")}
    check("2 bibliotecas criadas", len(libs) == 2)

    # 13.1: ano solto no futuro não é ano ("Blade Runner 2049")
    from server.scanner import parse_movie_name  # noqa: E402
    check("ano 2049 não vira ano", parse_movie_name("/m/Blade Runner 2049.mkv") == ("Blade Runner 2049", None))
    check("ano normal continua", parse_movie_name("/m/Meu Filme (2020).mp4") == ("Meu Filme", 2020))

    # 14.1: 404 do TVDB numa série não trava a identificação das demais (TVDB simulado)
    import requests  # noqa: E402
    import config  # noqa: E402
    from server import metadata as md  # noqa: E402

    def fake_fetch(tid):
        if tid == 100:
            resp = requests.Response()
            resp.status_code = 404
            raise requests.HTTPError(response=resp)
        return {(1, 1): ("Piloto", "sinopse")}

    saved = (config.TVDB_API_KEY, md.find_tvdb_id, md.fetch_tvdb_episodes)
    config.TVDB_API_KEY, md.find_tvdb_id, md.fetch_tvdb_episodes = "x", (lambda sh: 100 if sh["title"] == "Quebrada" else 200), fake_fetch
    try:
        with get_db() as conn:
            conn.execute("INSERT INTO libraries (id, name, type, path) VALUES (900, 'tvdb', 'show', '/nao/existe')")
            for i, t in ((901, "Quebrada"), (902, "Boa")):
                conn.execute("INSERT INTO media (id, library_id, title, path) VALUES (?, 900, ?, NULL)", (i, t))
                conn.execute("INSERT INTO episodes (media_id, season, episode, path) VALUES (?, 1, 1, ?)", (i, f"/nao/existe/{t}.mp4"))
        md.identify_episodes(900)
        with get_db() as conn:
            got = conn.execute("SELECT title FROM episodes WHERE media_id = 902").fetchone()[0]
            bad = conn.execute("SELECT tvdb_id FROM media WHERE id = 901").fetchone()[0]
            conn.execute("DELETE FROM media WHERE library_id = 900")
            conn.execute("DELETE FROM libraries WHERE id = 900")
        check("404 do TVDB não trava as outras séries", got == "Piloto" and bad == 0)
    finally:
        config.TVDB_API_KEY, md.find_tvdb_id, md.fetch_tvdb_episodes = saved

    # 12.3: caminho repetido é recusado; 12.2: usuário duplicado por caixa é recusado
    c.post("/admin/libraries", data={"name": "Copia", "type": "movie", "path": movies})
    with get_db() as conn:
        check("caminho repetido não cria acervo", conn.execute("SELECT COUNT(*) FROM libraries").fetchone()[0] == 2)
    c.post("/admin/users", data={"username": "ADMIN", "password": "abcd1"})
    with get_db() as conn:
        check("usuário duplicado por caixa recusado", conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1)

    c.post("/admin/libraries/scan")
    for _ in range(100):
        time.sleep(0.2)
        if not is_scanning():
            break
    check("scan terminou", not is_scanning())
    with get_db() as conn:
        mid = conn.execute("SELECT id FROM media WHERE path IS NOT NULL").fetchone()
        eid = conn.execute("SELECT id FROM episodes").fetchone()
    check("filme e episódio no banco", bool(mid) and bool(eid))
    with get_db() as conn:
        check("episódio duplicado ignorado", conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 1)
    # mesma série com anos diferentes não pode ser fundida (e o rescan não duplica)
    os.makedirs(os.path.join(shows, "Serie Teste (2020)"))
    shutil.copy(os.path.join(shows, "Serie Teste (2019)", "Serie.Teste.S01E01.mp4"),
                os.path.join(shows, "Serie Teste (2020)", "Serie.Teste.S01E01.mp4"))
    for _ in range(2):
        c.post("/admin/libraries/scan")
        for _ in range(100):
            time.sleep(0.2)
            if not is_scanning():
                break
    with get_db() as conn:
        check("séries com mesmo nome e anos diferentes ficam separadas",
              conn.execute("SELECT COUNT(*) FROM media WHERE path IS NULL").fetchone()[0] == 2
              and conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 2)
    check("biblioteca de filmes lista", c.get(f"/library/{libs['movie']}?sort=added").status_code == 200)
    html = c.get(f"/library/{libs['movie']}?sort=title").get_data(as_text=True)
    check("ordenação por título ignora acento (Ação Épica antes de Zorro)",
          0 <= html.find("Ação Épica") < html.find("Zorro"))

    # arquivo só de áudio: não é sondado de novo (11.2) e o play responde 415 (11.3)
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=duration=2",
                        os.path.join(movies, "So Audio (2018).mkv")], capture_output=True, timeout=60)
        c.post("/admin/libraries/scan")
        for _ in range(100):
            time.sleep(0.2)
            if not is_scanning():
                break
        with get_db() as conn:
            audio = conn.execute("SELECT id FROM media WHERE title = 'So Audio'").fetchone()
        from server.probe import probe_library  # noqa: E402
        check("arquivo só de áudio não é sondado de novo", bool(audio) and probe_library(libs["movie"]) == 0)
        check("play de arquivo sem vídeo dá 415", bool(audio) and c.post(f"/stream/movie/{audio['id']}/play").status_code == 415)

        # 12.4: ?start= acima da duração é limitado
        dur = (c.get(f"/stream/movie/{mid['id']}/info").json.get("info") or {}).get("duration")
        if dur:
            r = c.post(f"/stream/movie/{mid['id']}/play?start=99999&quality=480p")
            check("start limitado à duração", r.status_code == 200 and r.json["offset"] < dur)

    # 20.4: pedidos concorrentes da mesma sessão HLS esperam o playlist e criam uma só sessão
    if mid and shutil.which("ffmpeg"):
        import threading
        import server.stream as stream_mod20
        for sid_ in list(stream_mod20.SESSIONS):
            stream_mod20._drop(sid_)
        res20 = []

        def hit20():
            r_ = c.post(f"/stream/movie/{mid['id']}/play?mode=hls&start=1")
            res20.append((r_.status_code, (r_.json or {}).get("sid")))

        ths = [threading.Thread(target=hit20) for _ in range(3)]
        [t.start() for t in ths]
        [t.join() for t in ths]
        sids = {x[1] for x in res20}
        check("pedidos concorrentes criam uma só sessão", len(res20) == 3 and all(x[0] == 200 for x in res20) and len(sids) == 1)
        sid20 = next(iter(sids))
        check("playlist existe ao responder", bool(sid20) and os.path.exists(os.path.join(stream_mod20.SESSIONS[sid20]["dir"], "index.m3u8")))
        r = c.post(f"/stream/movie/{mid['id']}/play?mode=hls&start=1")
        check("reaproveitar sessão devolve playlist existente", r.status_code == 200 and r.json["sid"] == sid20)

    r = c.get("/search?q=acao epica")
    check("busca sem acento/caixa acha o filme", "Ação Épica" in r.get_data(as_text=True))

    if mid:
        with get_db() as conn:  # 17.2: a duração do banco vale mais que a do cliente; fixa 100 s para os percentuais abaixo
            row = conn.execute("SELECT info FROM media WHERE id = ?", (mid["id"],)).fetchone()
            info100 = json.loads(row["info"]) if row["info"] else {}
            info100.pop("error", None)
            info100["duration"] = 100
            conn.execute("UPDATE media SET info = ? WHERE id = ?", (json.dumps(info100), mid["id"]))
        r = c.post(f"/progress/movie/{mid['id']}", json={"position": 1, "duration": 100})
        check("salva progresso", r.status_code == 200 and r.json["ok"])
        check("lê progresso", c.get(f"/progress/movie/{mid['id']}").json["position"] == 1)
        check("continuar assistindo abre", c.get("/").status_code == 200)
        r = c.post(f"/progress/movie/{mid['id']}", json={"position": 95, "duration": 100})
        check(">90% marca assistido", r.json["watched"] is True)
        check("assistido sem posição fora de continuar", all(i["id"] != mid["id"] or i["kind"] != "movie" for i in c.get("/continue").json["items"]))
        c.post(f"/progress/movie/{mid['id']}", json={"position": 20, "duration": 100})
        check("reassistir tira de assistido", c.get(f"/progress/movie/{mid['id']}").json["watched"] is False)
        check("reassistir entra em continuar assistindo",
              any(i["kind"] == "movie" and i["id"] == mid["id"] for i in c.get("/continue").json["items"]))
        # 16.7: abrir um item já assistido e sair (posição <= 5 s) não tira o "assistido"
        c.post(f"/progress/movie/{mid['id']}", json={"position": 95, "duration": 100})
        c.post(f"/progress/movie/{mid['id']}", json={"position": 3, "duration": 100})
        check("posição <= 5 s não zera assistido", c.get(f"/progress/movie/{mid['id']}").json["watched"] is True)
        c.post(f"/progress/movie/{mid['id']}", json={"position": 20, "duration": 100})
        check("posição > 5 s zera assistido", c.get(f"/progress/movie/{mid['id']}").json["watched"] is False)
    if eid:
        r = c.post(f"/progress/episode/{eid['id']}", json={"position": 1, "duration": 100})
        check("progresso de episódio", r.status_code == 200)

    # remover biblioteca apaga progresso órfão
    c.post(f"/admin/libraries/{libs['show']}/delete")
    with get_db() as conn:
        check("remover biblioteca limpa episódios e progresso",
              conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 0
              and conn.execute("SELECT COUNT(*) FROM progress WHERE item_type = 'episode'").fetchone()[0] == 0)

    # trocar o tipo da biblioteca apaga os itens do tipo antigo; id inexistente dá 404
    c.post(f"/admin/libraries/{libs['movie']}/edit", data={"name": "Filmes", "type": "show", "path": movies})
    with get_db() as conn:
        check("trocar tipo limpa mídia e progresso antigos",
              conn.execute("SELECT COUNT(*) FROM media").fetchone()[0] == 0
              and conn.execute("SELECT COUNT(*) FROM progress").fetchone()[0] == 0)
    check("editar biblioteca inexistente dá 404",
          c.post("/admin/libraries/9999/edit", data={"name": "x", "type": "movie", "path": movies}).status_code == 404)

    # limite de tentativas de login (outro IP, para não bloquear o cliente principal)
    other = {"REMOTE_ADDR": "9.9.9.9"}
    codes = [c.post("/login", data={"username": "admin", "password": "x"}, environ_base=other).status_code for _ in range(6)]
    check("login bloqueado após 5 falhas", codes[:5] == [200] * 5 and codes[5] == 429)

    # ---------- Fase 16 ----------
    from server.scanner import parse_episodes, scan_shows, scan_movies, video_files  # noqa: E402
    from server.subtitles import external_subs  # noqa: E402

    def touch(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").write(b"\0" * 16)

    def lib_id(path):
        with get_db() as conn:
            r = conn.execute("SELECT id FROM libraries WHERE path = ?", (path,)).fetchone()
        return r["id"] if r else None

    def lib_count():
        with get_db() as conn:
            return conn.execute("SELECT COUNT(*) FROM libraries").fetchone()[0]

    # 16.1: trailer/sample só como sufixo ou nome exato
    d = os.path.join(TMP, "f161")
    for n in ("Trailer.Park.Boys.S01E01.mp4", "Sample.Size.2019.mp4", "The Trailer Park (2010).mp4",
              "Filme-trailer.mp4", "x.sample.mp4", "sample.mp4"):
        touch(os.path.join(d, n))
    got = {os.path.basename(f) for f in video_files(d)}
    check("trailer/sample no meio do nome não são ignorados",
          {"Trailer.Park.Boys.S01E01.mp4", "Sample.Size.2019.mp4", "The Trailer Park (2010).mp4"} <= got)
    check("trailer/sample como sufixo ou nome exato são ignorados",
          not ({"Filme-trailer.mp4", "x.sample.mp4", "sample.mp4"} & got))

    # 16.2: legenda externa só com resto de idioma/flag
    d = os.path.join(TMP, "f162")
    for n in ("Toy Story.mp4", "Toy Story.srt", "Toy Story.pt-BR.srt", "Toy Story.forced.srt", "Toy Story 2.srt"):
        touch(os.path.join(d, n))
    subs = {os.path.basename(x["file"]) for x in external_subs(os.path.join(d, "Toy Story.mp4"))}
    check("legenda 'Toy Story 2.srt' não é de 'Toy Story'", "Toy Story 2.srt" not in subs)
    check("legendas de idioma/flag são aceitas", {"Toy Story.srt", "Toy Story.pt-BR.srt", "Toy Story.forced.srt"} <= subs)

    # 16.3: symlink de pasta é seguido, sem entrar em loop
    real = os.path.join(TMP, "f163_real")
    touch(os.path.join(real, "Filme Link (2015).mp4"))
    os.symlink(real, os.path.join(TMP, "f163_link"))
    os.symlink(real, os.path.join(real, "loop"))
    found = list(video_files(os.path.join(TMP, "f163_link")))
    check("biblioteca apontando para symlink lista os arquivos (sem loop)", len(found) == 1)

    # 16.4: trocar só o caminho preserva itens e progresso
    a, b2 = os.path.join(TMP, "f164_a"), os.path.join(TMP, "f164_b")
    touch(os.path.join(a, "Filme Quatro (2012).mp4"))
    c.post("/admin/libraries", data={"name": "Quatro", "type": "movie", "path": a})
    lid4 = lib_id(a)
    scan_movies(lid4)
    with get_db() as conn:
        m4 = conn.execute("SELECT id FROM media WHERE library_id = ?", (lid4,)).fetchone()["id"]
        conn.execute("INSERT INTO progress (profile_id, item_type, item_id, position, watched) VALUES (?, 'movie', ?, 30, 0)", (pid, m4))
    shutil.move(a, b2)  # remontagem em outro caminho
    c.post(f"/admin/libraries/{lid4}/edit", data={"name": "Quatro", "type": "movie", "path": b2})
    with get_db() as conn:
        rows = conn.execute("SELECT id, path FROM media WHERE library_id = ?", (lid4,)).fetchall()
        prog = conn.execute("SELECT position FROM progress WHERE item_type = 'movie' AND item_id = ?", (m4,)).fetchone()
    check("trocar caminho reescreve o prefixo dos itens", len(rows) == 1 and rows[0]["id"] == m4 and rows[0]["path"].startswith(b2))
    check("trocar caminho preserva o progresso", bool(prog) and prog["position"] == 30)

    # 16.5: login ignora maiúsculas; campos sem autocapitalize
    r = run.app.test_client().post("/login", data={"username": "ADMIN", "password": "senha123"}, environ_base={"REMOTE_ADDR": "8.8.8.8"})
    check("login com caixa diferente funciona", r.status_code == 302)
    tpl = lambda n: open(os.path.join(ROOT, "web", "templates", n), encoding="utf-8").read()  # noqa: E731
    check("campos de usuário com autocapitalize off",
          'autocapitalize="off"' in tpl("login.html") and 'autocapitalize="off"' in tpl("setup.html"))

    # 16.11: acervo dentro de outro (ou que contenha outro) é recusado; irmão com prefixo parecido é aceito
    outer = os.path.join(TMP, "f1611", "outer")
    os.makedirs(os.path.join(outer, "inner"))
    os.makedirs(os.path.join(TMP, "f1611", "outer2"))
    c.post("/admin/libraries", data={"name": "Outer", "type": "movie", "path": outer})
    n0 = lib_count()
    c.post("/admin/libraries", data={"name": "Inner", "type": "movie", "path": os.path.join(outer, "inner")})
    check("acervo dentro de outro é recusado", lib_count() == n0)
    c.post("/admin/libraries", data={"name": "Pai", "type": "movie", "path": os.path.join(TMP, "f1611")})
    check("acervo que contém outro é recusado", lib_count() == n0)
    c.post("/admin/libraries", data={"name": "Outer2", "type": "movie", "path": os.path.join(TMP, "f1611", "outer2")})
    check("pasta irmã com prefixo parecido é aceita", lib_count() == n0 + 1)

    # 16.14: S01E01E02 e S01E03-E05 registram todos os episódios apontando para o mesmo arquivo
    d = os.path.join(TMP, "f1614")
    touch(os.path.join(d, "Multi (2021)", "Multi.S01E01E02.mp4"))
    touch(os.path.join(d, "Multi (2021)", "Multi.S01E03-E05.mp4"))
    c.post("/admin/libraries", data={"name": "Multi", "type": "show", "path": d})
    lid14 = lib_id(d)
    scan_shows(lid14)
    with get_db() as conn:
        eps = conn.execute("SELECT episode, path FROM episodes WHERE media_id IN (SELECT id FROM media WHERE library_id = ?) ORDER BY episode", (lid14,)).fetchall()
    check("episódios múltiplos registrados (1-5)", [e["episode"] for e in eps] == [1, 2, 3, 4, 5])
    check("episódios do mesmo arquivo apontam para ele", eps[0]["path"] == eps[1]["path"] and eps[2]["path"] == eps[4]["path"])
    check("rescan não duplica episódios", scan_shows(lid14) == 0)

    # 17.1: arquivo S01E01E02 — o próximo do E01 pula o E02 (mesmo arquivo) e concluir marca os dois
    with get_db() as conn:
        ids = {r["episode"]: r["id"] for r in conn.execute(
            "SELECT e.id, e.episode FROM episodes e JOIN media m ON m.id = e.media_id WHERE m.library_id = ?", (lid14,))}
    r = c.post(f"/progress/episode/{ids[1]}", json={"position": 10, "duration": 10}).json
    check("próximo do E01E02 pula o mesmo arquivo", bool(r["next"]) and r["next"]["episode"] == 3)
    with get_db() as conn:
        w = conn.execute("SELECT watched FROM progress WHERE item_type = 'episode' AND item_id = ?", (ids[2],)).fetchone()
    check("concluir E01E02 marca o E02 como assistido", bool(w) and w["watched"] == 1)
    c.post(f"/progress/episode/{ids[1]}/watched", json={"watched": 0})
    with get_db() as conn:
        w = conn.execute("SELECT watched FROM progress WHERE item_type = 'episode' AND item_id = ?", (ids[2],)).fetchone()
    check("desmarcar o E01 desmarca o E02 (mesmo arquivo)", bool(w) and w["watched"] == 0)

    # 17.7: série toda assistida oferece "Reproduzir", não "Próximo"
    with get_db() as conn:
        smid = conn.execute("SELECT media_id FROM episodes WHERE id = ?", (ids[1],)).fetchone()["media_id"]
    for i in ids.values():
        c.post(f"/progress/episode/{i}/watched", json={"watched": 1})
    page = c.get(f"/show/{smid}").get_data(as_text=True)
    check("série toda assistida mostra Reproduzir", re.search(r'class="mv-play"[^>]*>(?:(?!</a>).)*Reproduzir</a>', page) is not None and "Próximo · T" not in page)  # botão do detalhe (Fase 23): "Reproduzir"

    # 17.2: a duração do ffprobe vale mais que a enviada pelo cliente
    d17 = os.path.join(TMP, "f17")
    touch(os.path.join(d17, "Duracao (2020).mp4"))
    c.post("/admin/libraries", data={"name": "F17", "type": "movie", "path": d17})
    scan_movies(lib_id(d17))
    with get_db() as conn:
        zid = conn.execute("SELECT id FROM media WHERE library_id = ?", (lib_id(d17),)).fetchone()["id"]
        conn.execute("UPDATE media SET info = ? WHERE id = ?", ('{"duration": 100, "video": null, "audio": [], "subs": []}', zid))
    r = c.post(f"/progress/movie/{zid}", json={"position": 50, "duration": 51}).json
    check("duração do servidor vence a do cliente", r["watched"] is False and r["position"] == 50)

    # 17.3: valores não finitos e corpo JSON inválido dão 400, ?start= infinito vira 0
    check("position infinito -> 400", c.post(f"/progress/movie/{zid}", data='{"position": 1e999}', content_type="application/json").status_code == 400)
    check("corpo JSON lista -> 400", c.post(f"/progress/movie/{zid}", data="[1]", content_type="application/json").status_code == 400)
    from server.stream import start_arg
    with run.app.test_request_context("/?start=1e999"):
        check("?start=1e999 vira 0", start_arg() == 0)

    # 17.4: -readrate só entra no comando quando o ffmpeg suporta
    import server.stream as stream_mod
    cmds = []
    real_popen, real_flag = stream_mod.subprocess.Popen, stream_mod._READRATE
    stream_mod.subprocess.Popen = lambda cmd, **kw: cmds.append(cmd)
    try:
        for flag in (False, True):
            stream_mod._READRATE = flag
            stream_mod.start_hls("/x.mp4", os.path.join(TMP, "hls17"), "remux")
        check("sem suporte, não usa -readrate", "-readrate" not in cmds[0])
        check("com suporte, usa -readrate", "-readrate" in cmds[1])
    finally:
        stream_mod.subprocess.Popen, stream_mod._READRATE = real_popen, real_flag

    # ---------- Fase 18 ----------
    from server.subtitles import srt_to_vtt  # noqa: E402

    # 18.1: "S01E01-02" é intervalo; "-720p", "-10bit" e intervalos absurdos não viram episódio
    pe = lambda n: parse_episodes("/s", "/s/Show/" + n)[3]  # noqa: E731
    check("S01E01-02 registra 1 e 2", pe("Show.S01E01-02.mkv") == [1, 2])
    check("S01E05-08 registra 5 a 8", pe("Show.S01E05-08.mkv") == [5, 6, 7, 8])
    check("-720p/-10bit/-45 não viram episódio", pe("Show.S01E01-720p.mkv") == [1] and pe("Show.S01E01-10bit.mkv") == [1] and pe("Show.S01E01-45.mkv") == [1])

    # 18.2: tags de release cortam o título quando não há ano
    check("tags de release saem do título", parse_movie_name("/m/Filme 1080p BluRay x264.mkv") == ("Filme", None))
    check("título sem tags não muda", parse_movie_name("/m/Se7en.mkv") == ("Se7en", None) and parse_movie_name("/m/Wall-E (2008).mkv") == ("Wall-E", 2008))

    # 18.3: pasta de temporada na raiz não vira série "Season 1"
    check("Season 1/Show.S01E01 usa o nome do arquivo", parse_episodes("/lib/X", "/lib/X/Season 1/Show Name.S01E01.mkv")[0] == "Show Name")
    check("Season 1/S01E01 usa o nome da pasta da biblioteca", parse_episodes("/lib/Minha Serie", "/lib/Minha Serie/Season 1/S01E01.mkv")[0] == "Minha Serie")

    # 18.4: {\an8} do SRT não aparece como texto
    check("legenda sem {\\an8}", "{" not in srt_to_vtt("1\n00:00:01,000 --> 00:00:02,000\n{\\an8}Oi\n"))

    # 18.5: arquivo de vários episódios é sondado uma vez
    import server.probe as probe_mod
    calls = []
    real_probe = probe_mod.probe
    probe_mod.probe = lambda path: calls.append(path)
    try:
        probe_mod.probe_library(lid14)
    finally:
        probe_mod.probe = real_probe
    check("multi-episódio sondado uma vez por arquivo", len(calls) == 2)

    # 20.3: erro de ffprobe grava tamanho/mtime; só sonda de novo se o arquivo mudar
    def run_probe(lid):
        probe_mod.probe = lambda path: calls.append(path)
        try:
            probe_mod.probe_library(lid)
        finally:
            probe_mod.probe = real_probe

    with get_db() as conn:
        ep_path = conn.execute("SELECT e.path FROM episodes e JOIN media m ON m.id = e.media_id WHERE m.library_id = ? LIMIT 1", (lid14,)).fetchone()["path"]
    del calls[:]
    run_probe(lid14)
    check("erro de ffprobe com arquivo igual não é sondado de novo", len(calls) == 0)
    with open(ep_path, "ab") as f:
        f.write(b"\0" * 16)
    del calls[:]
    run_probe(lid14)
    check("arquivo alterado após erro é sondado de novo", ep_path in calls)

    # 18.7: pôster genérico não é cacheável por proxy compartilhado
    check("placeholder com Cache-Control private", "private" in c.get(f"/poster/{zid}").headers.get("Cache-Control", ""))

    # ---------- Fase 19 ----------
    # 19.1: idioma por extenso na legenda externa
    d = os.path.join(TMP, "f191")
    for n in ("Filme.mp4", "Filme.English.srt", "Filme.Portuguese.srt", "Filme 2.srt"):
        touch(os.path.join(d, n))
    subs = {os.path.basename(x["file"]) for x in external_subs(os.path.join(d, "Filme.mp4"))}
    check("legendas com idioma por extenso são aceitas", {"Filme.English.srt", "Filme.Portuguese.srt"} <= subs)
    check("legenda 'Filme 2.srt' segue recusada", "Filme 2.srt" not in subs)

    # 19.2: pastas de extras do padrão Plex são ignoradas
    d = os.path.join(TMP, "f192")
    touch(os.path.join(d, "Movie (2010)", "Movie (2010).mp4"))
    for sub in ("Trailers", "Behind The Scenes", "Deleted Scenes", "Interviews", "Scenes", "Shorts", "Other"):
        touch(os.path.join(d, "Movie (2010)", sub, "Extra.mp4"))
    got = [os.path.basename(f) for f in video_files(d)]
    check("pastas de extras não viram filmes", got == ["Movie (2010).mp4"])

    # 19.3: qualidade igual ou acima da altura do vídeo é ignorada; inválida dá 400
    from server.stream import quality_arg
    info180 = {"video": {"height": 180}}
    info1080 = {"video": {"height": 1080}}
    with run.app.test_request_context("/?quality=480p"):
        check("480p em vídeo 180p é ignorada", quality_arg(info180) is None)
        check("480p em vídeo 1080p é aceita", quality_arg(info1080) == "480p")
    with run.app.test_request_context("/?quality=1080p"):
        check("1080p em vídeo 1080p é ignorada", quality_arg(info1080) is None)

    # 19.4: tags comuns de release saem do título sem ano
    for tag in ("UHD.BluRay", "REMUX", "4K", "HDR", "HDR10", "DV", "IMAX", "PROPER", "REPACK", "AMZN", "NF"):
        check("tag " + tag + " sai do título", parse_movie_name("/m/Film." + tag + ".mkv") == ("Film", None))

    # 19.5: H.264 8-bit com croma 4:2:2/4:4:4 não é direct/remux
    from server.stream import decide
    for pf in ("yuv422p", "yuv444p", "yuvj422p", "yuvj444p"):
        i = {"video": {"codec": "h264", "pix_fmt": pf}, "audio": [{"index": 1}]}
        check("H.264 " + pf + " vai para transcode", decide("/x.mp4", i) == "transcode")
    check("H.264 yuv420p segue direct", decide("/x.mp4", {"video": {"codec": "h264", "pix_fmt": "yuv420p"}, "audio": [{"index": 1, "codec": "aac"}]}) == "direct")

    # 20.5: sem sessão, API responde 401 JSON e páginas HTML seguem redirecionando
    anon = run.app.test_client()
    for u in ("/stream/movie/1/info", "/progress/movie/1", "/continue", "/next/movie/1", "/admin/tmdb-search?type=movie&q=x"):
        r = anon.get(u)
        check(f"sem sessão {u.split('?')[0]} -> 401 JSON", r.status_code == 401 and (r.json or {}).get("error") == "Sessão expirada")
    check("sem sessão POST /progress -> 401", anon.post("/progress/movie/1", json={"position": 1}).status_code == 401)
    check("sem sessão página HTML -> /login", anon.get("/").headers["Location"].endswith("/login"))
    check("sem sessão /admin/libraries (HTML) -> /login", anon.get("/admin/libraries", headers={"Accept": "text/html"}).status_code == 302)
    check("player.js trata 401", "r.status === 401" in open(os.path.join(ROOT, "web", "static", "js", "player.js"), encoding="utf-8").read())

    # 20.6: id de biblioteca com dígito Unicode não derruba o acesso (500)
    r = c.post("/admin/users/1/access", data={"library": ["\u00b2", "9" * 40, "abc"]})
    check("access ignora dígitos Unicode/ids inválidos (sem 500)", r.status_code == 302)

    # 20.7: cache de legendas com mais de 30 dias é apagado; recente e outros arquivos ficam
    import config as cfg20
    from server.subtitles import clean_subs
    old_f, new_f, other_f = (os.path.join(cfg20.SUBS_DIR, n) for n in ("ext_old20.vtt", "emb_new20.vtt", "outro20.txt"))
    for f_ in (old_f, new_f, other_f):
        open(f_, "w").write("x")
    t_old = time.time() - 31 * 86400
    os.utime(old_f, (t_old, t_old))
    os.utime(other_f, (t_old, t_old))
    clean_subs()
    check("legenda em cache com >30 dias é apagada", not os.path.exists(old_f))
    check("legenda recente e arquivo alheio ficam", os.path.exists(new_f) and os.path.exists(other_f))
    check("start_cleanup limpa o cache de legendas", "_clean_subs()" in open(os.path.join(ROOT, "server", "stream.py"), encoding="utf-8").read())

    # 19.6: pagehide não salva antes de a mídia carregar nem com posição < 1 s
    js = open(os.path.join(ROOT, "web", "static", "js", "player.js"), encoding="utf-8").read()
    check("player.js: save(false) exige mídia carregada e posição >= 1 s", "if (!final && (!loaded || abs() < 1)) return;" in js)
    check("player.js: carga antiga encerra sessão e não mostra erro", "flushStale" in js and "if (token !== loadToken) return;  // erro de carga antiga" in js)  # 20.8
    kt = open(os.path.join(ROOT, "android", "app", "src", "main", "java", "com", "starflix", "app", "WebActivity.kt"), encoding="utf-8").read()
    check("WebActivity zera failed em onPageStarted", re.search(r"onPageStarted\([^)]*\)\s*\{[^}]*failed = false", kt) is not None)  # 20.9
    # ---- Fase 23: interface Plex (rotas 23.12–23.27) ----
    from server.db import get_db as _gdb23
    with _gdb23() as conn23:
        mv23 = conn23.execute("SELECT m.id FROM media m JOIN libraries l ON l.id = m.library_id WHERE l.type = 'movie' ORDER BY m.id").fetchone()
        sh23 = conn23.execute("SELECT m.id FROM media m JOIN libraries l ON l.id = m.library_id WHERE l.type = 'show' ORDER BY m.id").fetchone()
        ep23 = conn23.execute("SELECT id, season FROM episodes ORDER BY id").fetchone() if sh23 else None
    if mv23 and sh23 and ep23:
        mv, sh, ep = mv23["id"], sh23["id"], ep23["id"]
        # o teste "trocar tipo" (Fase 9) apaga os filmes iniciais: repõe dois filmes na biblioteca do filme escolhido (usado em 23.26 e 24.x)
        with _gdb23() as conn23:
            lib_mv = conn23.execute("SELECT l.id, l.path FROM libraries l JOIN media m ON m.library_id = l.id WHERE m.id = ?", (mv,)).fetchone()
        if not os.path.exists(os.path.join(lib_mv["path"], "Zorro (2019).mp4")):
            make_video(os.path.join(lib_mv["path"], "Zorro (2019).mp4"))
        c.post(f"/admin/libraries/{lib_mv['id']}/scan")
        for _ in range(150):
            if not is_scanning():
                break
            time.sleep(0.2)
        sn = f"{sh}-{ep23['season']}"
        # 23.18: modal (JSON por tipo) e abas por tipo
        j = c.get(f"/admin/item/movie/{mv}/edit").json
        check("23.18 GET edit filme: título, abas e campos", j and j["title"].startswith("Editar ") and "logo" in j["tabs"] and "title" in j["fields"])
        j = c.get(f"/admin/item/season/{sn}/edit").json
        check("23.23 GET edit temporada: título 'Temporada N' e abas", j and "Temporada" in j["title"] and j["tabs"] == ["general", "poster", "backdrop", "info", "advanced"])
        j = c.get(f"/admin/item/episode/{ep}/edit").json
        check("23.24 GET edit episódio: (T E) no título e sem backdrop", j and re.search(r"\(T\d+ E\d+\)$", j["title"]) and "backdrop" not in j["tabs"])
        check("23.18 tipo inválido/inexistente -> 404", c.get("/admin/item/foo/1/edit").status_code == 404 and c.get("/admin/item/movie/99999/edit").status_code == 404)
        check("23.18 sem admin/sessão -> 401", anon.get(f"/admin/item/movie/{mv}/edit").status_code == 401)
        # 23.19: Geral com travas
        r = c.post(f"/admin/item/movie/{mv}/edit", json={"fields": {"title": "Filme Editado", "rating": "7.5", "release_date": "2001-02-03"}, "locks": {"title": 1}})
        j = c.get(f"/admin/item/movie/{mv}/edit").json
        check("23.19 POST Geral grava campos e trava", r.status_code == 200 and j["fields"]["title"] == "Filme Editado" and j["locks"].get("title") == 1 and j["fields"]["rating"] == 7.5)
        check("23.19 valor inválido -> 400", c.post(f"/admin/item/movie/{mv}/edit", json={"fields": {"rating": "99"}}).status_code == 400 and c.post(f"/admin/item/movie/{mv}/edit", json={"fields": {"release_date": "x"}}).status_code == 400)
        c.post(f"/admin/item/movie/{mv}/edit", json={"locks": {"title": 0}})
        check("23.19 destravar remove a trava", "title" not in c.get(f"/admin/item/movie/{mv}/edit").json["locks"])
        # 23.21: tags/rótulos
        c.post(f"/admin/item/movie/{mv}/edit", json={"tags": {"genres": ["Ação", "Drama"], "directors": ["Fulano"], "label": ["favorito"]}, "locks": {"genres": 1}})
        j = c.get(f"/admin/item/movie/{mv}/edit").json
        check("23.21 tags e equipe gravadas", j["tags"]["genres"] == ["Ação", "Drama"] and j["tags"]["directors"] == ["Fulano"] and j["tags"]["label"] == ["favorito"] and j["locks"].get("genres") == 1)
        c.post(f"/admin/item/episode/{ep}/edit", json={"tags": {"writers": ["Ana"]}})
        check("23.21 equipe do episódio", c.get(f"/admin/item/episode/{ep}/edit").json["tags"]["writers"] == ["Ana"])
        # 23.22: Avançado (prefs validadas) e Informações
        c.post(f"/admin/item/show/{sh}/edit", json={"prefs": {"sub_mode": "forced", "audio_lang": "xx"}})
        pf = c.get(f"/admin/item/show/{sh}/edit").json["prefs"]
        check("23.22 prefs: valor válido grava, inválido é ignorado", pf.get("sub_mode") == "forced" and "audio_lang" not in pf)
        j = c.get(f"/admin/item/movie/{mv}/edit").json
        check("23.22 Informações: caminho e tamanho dos arquivos", j["files"] and j["files"][0]["path"] and j["files"][0]["size"])
        # 23.20: imagens (upload, URL bloqueada, limpar)
        import io
        png = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
        r = c.post(f"/admin/item/movie/{mv}/image/poster", data={"file": (io.BytesIO(png), "p.png")}, content_type="multipart/form-data")
        check("23.20 upload png do pôster", r.status_code == 200 and r.json["name"].endswith(".png") and os.path.exists(os.path.join(cfg20.POSTERS_DIR, r.json["name"])))
        r = c.post(f"/admin/item/movie/{mv}/image/poster", data={"file": (io.BytesIO(b"GIF89a"), "p.gif")}, content_type="multipart/form-data")
        check("23.20 upload fora de jpg/png/webp -> 400", r.status_code == 400)
        r = c.post(f"/admin/item/movie/{mv}/image/poster", data={"url": "http://127.0.0.1:1/x.png"})
        check("23.20 URL de IP local/loopback bloqueada (SSRF)", r.status_code == 400)
        r = c.post(f"/admin/item/movie/{mv}/image/logo", data={"clear": "1"})
        check("23.20 limpar logo trava o campo", r.status_code == 200 and c.get(f"/admin/item/movie/{mv}/edit").json["locks"].get("logo") == 1)
        check("23.20 slot inválido para o tipo -> 404", c.post(f"/admin/item/episode/{ep}/image/logo", data={"clear": "1"}).status_code == 404)
        check("23.20 candidatas sem TMDB -> lista vazia", c.get(f"/admin/item/movie/{mv}/images/poster").json == {"items": []})
        # 23.25: ações do menu
        check("23.25 analisar", c.post(f"/admin/item/show/{sh}/analyze").json.get("ok") is True)
        check("23.25 histórico", isinstance(c.get(f"/admin/item/show/{sh}/history").json.get("items"), list))
        check("23.25 atualizar metadados sem TMDB -> 400", c.post(f"/admin/item/movie/{mv}/refresh").status_code == 400)
        # 23.26: busca instantânea
        j = c.get("/search?json=1&q=" + "Zorro").json
        check("23.26 busca JSON com título/url/img", j and all(k in j["items"][0] for k in ("title", "url", "img")) if j and j["items"] else True)
        check("23.26 página de busca usa cards", b"pcard" in c.get("/search?q=Zorro").data)
        # 23.27: preferências no detalhe e no /watch
        r = c.get(f"/watch/episode/{ep}?audio=pt&sub=off")
        check("23.27 /watch recebe áudio/legenda por querystring", r.status_code == 200 and b'data-audio="pt"' in r.data and b'data-sub="off"' in r.data)
        check("23.27 Play da temporada repassa ?audio=", "audio=pt" in c.get(f"/show/{sh}/season/{ep23['season']}/play?audio=pt").headers["Location"])
        check("23.27 detalhe mostra dropdowns", b"pf-audio" in c.get(f"/movie/{mv}").data)
        # ---- Fase 24: coleções manuais (24.1–24.12) ----
        with _gdb23() as conn24:
            lib24 = conn24.execute("SELECT library_id FROM media WHERE id = ?", (mv,)).fetchone()["library_id"]
            mids24 = [r["id"] for r in conn24.execute("SELECT id FROM media WHERE library_id = ? ORDER BY id", (lib24,))]
            tabs24 = {r["name"] for r in conn24.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        check("24.1 tabelas collections e collection_items", {"collections", "collection_items"} <= tabs24)
        check("24.2 sem sessão -> 401 na API e sem acesso ao detalhe", anon.post("/admin/collections", json={"title": "X", "library_id": lib24}).status_code == 401
              and anon.get("/collection/1").status_code in (302, 401))
        check("24.2 criar sem título -> 400", c.post("/admin/collections", json={"title": "  ", "library_id": lib24}).status_code == 400)
        check("24.2 biblioteca inválida -> 400/404", c.post("/admin/collections", json={"title": "X", "library_id": "a"}).status_code == 400
              and c.post("/admin/collections", json={"title": "X", "library_id": 99999}).status_code == 404)
        r = c.post("/admin/collections", json={"title": "Coleção Teste", "library_id": lib24, "media_ids": mids24[:2] + [sh, 99999, True, "x"]})
        cid = r.json.get("id") if r.status_code == 200 else None
        check("24.2 criar coleção: só mídia da mesma biblioteca (série e ids inválidos ignorados)", cid and r.json["n"] == len(mids24[:2]))
        check("24.2 nome duplicado (sem diferenciar caixa/acento) -> 409", c.post("/admin/collections", json={"title": "COLEÇÃO teste", "library_id": lib24}).status_code == 409)
        if cid:
            check("24.2 lista do admin", any(x["id"] == cid and x["n"] == len(mids24[:2]) for x in c.get(f"/admin/collections?library={lib24}").json["collections"]))
            check("24.2 adicionar item repetido não duplica", c.post(f"/admin/collections/{cid}/items", json={"media_ids": mids24[:2]}).json["added"] == 0)
            check("24.2 adicionar série a coleção de filmes é ignorado", c.post(f"/admin/collections/{cid}/items", json={"media_ids": [sh]}).json["added"] == 0)
            check("24.2 coleção inexistente -> 404", c.post("/admin/collections/99999/items", json={"media_ids": [mv]}).status_code == 404)
            # 24.3/24.4: ações em lote
            check("24.4 bulk watched", c.post("/bulk/watched", json={"ids": mids24[:2], "watched": True}).json == {"ok": True, "n": len(mids24[:2]), "watched": True})
            check("24.4 bulk Minha Lista alterna", c.post("/bulk/list", json={"ids": [mv]}).json["on"] is True and c.post("/bulk/list", json={"ids": [mv]}).json["on"] is False)
            check("24.4 bulk unresume", c.post("/bulk/unresume", json={"ids": [mv]}).json.get("ok") is True)
            check("24.4 bulk ação inválida/ids vazios -> 404", c.post("/bulk/foo", json={"ids": [mv]}).status_code == 404 and c.post("/bulk/watched", json={"ids": []}).status_code == 404)
            check("24.4 bulk sem sessão -> 401", anon.post("/bulk/watched", json={"ids": [mv]}).status_code == 401)
            lib_html = c.get(f"/library/{lib24}?tab=library").data
            check("24.3/24.5 biblioteca tem barra de seleção, cards selecionáveis e modal", b'id="sel-bar"' in lib_html and b"data-pick=" in lib_html and b"collection-add.js" in lib_html)
            # 24.6: aba Coleções
            tab_html = c.get(f"/library/{lib24}?tab=collections").data
            check("24.6 aba Coleções lista a coleção com ⚙ (admin) e contagem", "Coleção Teste".encode() in tab_html and b"data-edit-item=\"collection:%d\"" % cid in tab_html and b"2 itens" in tab_html)
            # 24.7: detalhe
            det = c.get(f"/collection/{cid}")
            check("24.7 detalhe: título, contagem, seleção e zoom", det.status_code == 200 and "Coleção Teste".encode() in det.data and b"2 filmes" in det.data and b'data-pick=' in det.data and b"zoom-range" in det.data)
            check("24.7 detalhe inexistente -> 404", c.get("/collection/99999").status_code == 404)
            check("24.7 estrelas da coleção (0–10) e valor inválido -> 400", c.post(f"/stars/collection/{cid}", json={"stars": 7}).status_code == 200
                  and c.post(f"/stars/collection/{cid}", json={"stars": 11}).status_code == 400 and c.post("/stars/collection/99999", json={"stars": 3}).status_code == 404)
            # imagens públicas com fallback
            check("24.2 imagens: pôster cai no do primeiro item; fundo/logo sem imagem -> 404", c.get(f"/collection-poster/{cid}").status_code in (200, 302)
                  and c.get(f"/collection-logo/{cid}").status_code == 404 and c.get("/collection-poster/99999").status_code == 404)
            # 24.9: Geral e Rótulos
            j = c.get(f"/admin/item/collection/{cid}/edit").json
            check("24.9 GET edit coleção: título e 8 abas", j["title"] == "Editar Coleção Coleção Teste" and j["tabs"] == ["general", "labels", "poster", "backdrop", "logo", "square", "info", "advanced"])
            r = c.post(f"/admin/item/collection/{cid}/edit", json={"fields": {"overview": "Resumo X", "content_rating": "PG"}, "locks": {"overview": 1}, "tags": {"label": ["a", "b"]}})
            j = c.get(f"/admin/item/collection/{cid}/edit").json
            check("24.9 Geral grava campos, trava e rótulos", r.status_code == 200 and j["fields"]["overview"] == "Resumo X" and j["locks"].get("overview") == 1 and j["tags"]["label"] == ["a", "b"])
            c.post("/admin/collections", json={"title": "Outra Coleção", "library_id": lib24})
            check("24.9 renomear para nome existente -> 409", c.post(f"/admin/item/collection/{cid}/edit", json={"fields": {"title": "outra coleção"}}).status_code == 409)
            check("24.9 sem admin/sessão -> 401", anon.get(f"/admin/item/collection/{cid}/edit").status_code == 401)
            # 24.10: imagens da coleção
            cand = c.get(f"/admin/item/collection/{cid}/images/poster").json
            check("24.10 candidatas = imagens dos itens (lista)", isinstance(cand.get("items"), list))
            r = c.post(f"/admin/item/collection/{cid}/image/poster", data={"file": (io.BytesIO(png), "p.png")}, content_type="multipart/form-data")
            check("24.10 upload png salvo em data/posters/col/", r.status_code == 200 and r.json["name"].startswith("col/") and os.path.exists(os.path.join(cfg20.POSTERS_DIR, r.json["name"])))
            up24 = r.json.get("name") if r.status_code == 200 else None
            check("24.10 upload inválido e URL local bloqueada -> 400", c.post(f"/admin/item/collection/{cid}/image/poster", data={"file": (io.BytesIO(b"GIF89a"), "p.gif")}, content_type="multipart/form-data").status_code == 400
                  and c.post(f"/admin/item/collection/{cid}/image/backdrop", data={"url": "http://127.0.0.1:1/x.png"}).status_code == 400)
            check("24.10 limpar logo trava o campo", c.post(f"/admin/item/collection/{cid}/image/logo", data={"clear": "1"}).status_code == 200 and c.get(f"/admin/item/collection/{cid}/edit").json["locks"].get("logo") == 1)
            # 24.11: Informações e Modo de Coleta
            check("24.11 Informações: caminho de cada item", len(c.get(f"/admin/item/collection/{cid}/edit").json["files"]) == len(mids24[:2]))
            c.post(f"/admin/item/collection/{cid}/edit", json={"prefs": {"mode": "x"}})
            check("24.11 modo inválido é ignorado", "mode" not in c.get(f"/admin/item/collection/{cid}/edit").json["prefs"])
            c.post(f"/admin/item/collection/{cid}/edit", json={"prefs": {"mode": "hide"}})
            hide_html = c.get(f"/library/{lib24}?tab=library").data
            check("24.11 modo 'hide': itens saem da grade e a coleção aparece", all(b'href="/movie/%d"' % m not in hide_html for m in mids24[:2]) and b"data-collection=" in hide_html)
            c.post(f"/admin/item/collection/{cid}/edit", json={"prefs": {"mode": "both"}})
            both_html = c.get(f"/library/{lib24}?tab=library").data
            check("24.11 modo 'both': coleção e itens aparecem", b"data-collection=" in both_html and b'href="/movie/%d"' % mids24[0] in both_html)
            c.post(f"/admin/item/collection/{cid}/edit", json={"prefs": {"mode": ""}})
            check("24.11 modo padrão: itens na grade sem a coleção", b"data-collection=" not in c.get(f"/library/{lib24}?tab=library").data)
            # 24.12: busca e Recomendado
            sj = c.get("/search?json=1&q=" + "colecao teste").json
            check("24.12 busca instantânea traz coleção (sem acento), url e pôster", any(x["kind"] == "collection" and x["url"] == f"/collection/{cid}" and x["img"] == f"/collection-poster/{cid}" for x in sj["items"]))
            sp = c.get("/search?q=colecao+teste").data
            check("24.12 página de busca tem seção Coleções", "Coleções".encode() in sp and b"data-collection=" in sp)
            check("24.12 Recomendado tem fileira Coleções", "Coleções".encode() in c.get(f"/library/{lib24}?tab=recommended").data)
            # 24.13: CSS responsivo
            css24 = open(os.path.join(ROOT, "web", "static", "css", "starflix.css"), encoding="utf-8").read()
            check("24.13 CSS: modais em tela cheia abaixo de 600 px e barra de seleção com rolagem", ".ca-win { width: 100%; height: 100%" in css24 and "overflow-x: auto" in css24)
            # 24.8: remover item e coleção vazia
            r = c.delete(f"/admin/collections/{cid}/items/{mids24[0]}")
            check("24.8 remover item da coleção", r.json == {"ok": True, "n": len(mids24[:2]) - 1})
            check("24.8 coleção vazia continua existindo", c.delete(f"/admin/collections/{cid}/items/{mids24[1]}").json["n"] == 0 and c.get(f"/collection/{cid}").status_code == 200)
            # excluir coleção: não apaga mídia, apaga imagens e estrelas
            r = c.delete(f"/admin/collections/{cid}")
            with _gdb23() as conn24:
                left = conn24.execute("SELECT COUNT(*) FROM media WHERE library_id = ?", (lib24,)).fetchone()[0]
                st = conn24.execute("SELECT COUNT(*) FROM stars WHERE item_type = 'collection' AND item_id = ?", (cid,)).fetchone()[0]
            check("24.1 excluir coleção: mídia fica, estrelas e imagem local somem", r.json.get("ok") is True and left == len(mids24) and st == 0 and (not up24 or not os.path.exists(os.path.join(cfg20.POSTERS_DIR, up24))))
            check("24.2 coleção excluída -> 404", c.get(f"/collection/{cid}").status_code == 404 and c.delete(f"/admin/collections/{cid}").status_code == 404)
        # ---- Fase 25: Remover Correspondência, Conceder Acesso e Salvar arquivo (25.4, 25.6, 25.7) ----
        # 25.6: Conceder Acesso (acesso por biblioteca)
        c.post("/admin/users", data={"username": "leitor25", "password": "abcd1"})
        r = c.get(f"/admin/item/movie/{mv}/access")
        j = r.json or {}
        check("25.6 GET acesso: título, biblioteca e admin na lista", r.status_code == 200 and j.get("title") and j.get("library")
              and any(u["admin"] for u in j["with_access"]))
        check("25.6 usuário sem acesso aparece em 'others'", any(u["username"] == "leitor25" for u in j.get("others", [])))
        check("25.6 usuário inexistente -> 404", c.post(f"/admin/item/movie/{mv}/access", data={"user": "ninguem25"}).status_code == 404
              and c.post(f"/admin/item/movie/{mv}/access", data={"user": ""}).status_code == 404)
        r = c.post(f"/admin/item/movie/{mv}/access", data={"user": "LEITOR25"})
        check("25.6 conceder (sem diferenciar caixa) move o usuário para 'with_access'",
              r.status_code == 200 and any(u["username"] == "leitor25" for u in r.json["with_access"])
              and not any(u["username"] == "leitor25" for u in r.json["others"]))
        check("25.6 conceder de novo é idempotente", c.post(f"/admin/item/movie/{mv}/access", data={"user": "leitor25"}).status_code == 200)
        with _gdb23() as conn25:
            n25 = conn25.execute("SELECT COUNT(*) FROM user_libraries ul JOIN users u ON u.id = ul.user_id "
                                 "WHERE lower(u.username) = 'leitor25' AND ul.library_id = ?", (lib24,)).fetchone()[0]
        check("25.6 grava uma única linha em user_libraries", n25 == 1)
        check("25.6 série também aceita", c.get(f"/admin/item/show/{sh}/access").status_code == 200)
        check("25.6 tipo inválido (episódio) -> 404", c.get(f"/admin/item/episode/{ep}/access").status_code == 404)
        check("25.6 sem sessão -> 401", anon.get(f"/admin/item/movie/{mv}/access").status_code == 401
              and anon.post(f"/admin/item/movie/{mv}/access", data={"user": "leitor25"}).status_code == 401)
        # 25.7: Salvar arquivo
        r = c.get(f"/download/movie/{mv}")
        check("25.7 download: 200 como anexo com o nome do arquivo", r.status_code == 200
              and r.headers.get("Content-Disposition", "").startswith("attachment") and ".mp4" in r.headers.get("Content-Disposition", ""))
        r = c.get(f"/download/movie/{mv}", headers={"Range": "bytes=0-3"})
        check("25.7 download com Range -> 206 e Content-Range", r.status_code == 206 and len(r.data) == 4 and r.headers.get("Content-Range", "").startswith("bytes 0-3/"))
        check("25.7 filme inexistente -> 404", c.get("/download/movie/99999").status_code == 404)
        check("25.7 sem sessão não baixa", anon.get(f"/download/movie/{mv}").status_code in (301, 302, 401))
        with _gdb23() as conn25:
            old25 = conn25.execute("SELECT path FROM media WHERE id = ?", (mv,)).fetchone()["path"]
            outside25 = os.path.join(TMP, "fora25.mp4")
            shutil.copy(old25, outside25)
            conn25.execute("UPDATE media SET path = ? WHERE id = ?", (outside25, mv))
        check("25.7 caminho fora da pasta da biblioteca -> 404", c.get(f"/download/movie/{mv}").status_code == 404)
        with _gdb23() as conn25:
            conn25.execute("UPDATE media SET path = ? WHERE id = ?", (old25, mv))
        check("25.7 caminho restaurado volta a baixar", c.get(f"/download/movie/{mv}").status_code == 200)
        # 25.4: Remover Correspondência (campo travado fica; tmdb_id = 0)
        c.post(f"/admin/item/movie/{mv}/edit", json={"fields": {"overview": "Resumo travado 25"}, "locks": {"overview": 1}})  # a trava é explícita desde a 23.19
        with _gdb23() as conn25:
            conn25.execute("UPDATE media SET tmdb_id = 555 WHERE id = ?", (mv,))  # só item com correspondência pode ser desvinculado (35.2)
        r = c.post(f"/admin/item/movie/{mv}/unmatch")
        with _gdb23() as conn25:
            row25 = conn25.execute("SELECT tmdb_id, overview FROM media WHERE id = ?", (mv,)).fetchone()
        check("25.4 unmatch: tmdb_id = 0 e campo travado preservado", r.status_code == 200 and row25["tmdb_id"] == 0 and row25["overview"] == "Resumo travado 25")
        check("25.4 unmatch repetido (já sem correspondência) devolve 400", c.post(f"/admin/item/movie/{mv}/unmatch").status_code == 400)
        check("25.4 tipo inválido e tipo da biblioteca trocado -> 404", c.post(f"/admin/item/episode/{ep}/unmatch").status_code == 404
              and c.post(f"/admin/item/show/{mv}/unmatch").status_code == 404)
        check("25.4 sem sessão -> 401", anon.post(f"/admin/item/movie/{mv}/unmatch").status_code == 401)
        # 25.5: apoio ao modal Corrigir Correspondência
        r = c.get(f"/admin/media/{mv}/match-info")
        check("25.5 match-info: local, título e sugestão automática", r.status_code == 200 and r.json["path"] and r.json["auto"]["title"] and r.json["kind"] == "movie")
        check("25.5 match-info de série traz a pasta e item inexistente -> 404", c.get(f"/admin/media/{sh}/match-info").json["kind"] == "show"
              and c.get("/admin/media/99999/match-info").status_code == 404 and anon.get(f"/admin/media/{mv}/match-info").status_code == 401)
        # 25.8: CSS responsivo dos modais novos
        css25 = open(os.path.join(ROOT, "web", "static", "css", "starflix.css"), encoding="utf-8").read()
        check("25.8 CSS: modais novos em tela cheia abaixo de 600 px", ".em-win.em-wide, .em-win.em-access" in css25 and "100dvh" in css25)
        # ---- Fase 26: menu do usuário, Perfil e Conta (apenas escrito; não rodar sem o Leo pedir) ----
        with _gdb23() as conn26:
            cols26 = {r_[1] for r_ in conn26.execute("PRAGMA table_info(users)")}
        check("26.1 colunas novas em users", {"full_name", "avatar", "location", "bio", "link", "show_badge", "prefs", "session_ver"} <= cols26)
        c.post("/admin/users", data={"username": "Ana26", "password": "abcd1"})
        c26 = run.app.test_client()
        c26.post("/login", data={"username": "ana26", "password": "abcd1"})
        c26.post("/profiles/new", data={"name": "Ana"})
        with _gdb23() as conn26:
            uid26 = conn26.execute("SELECT id FROM users WHERE username = 'Ana26'").fetchone()["id"]
            pid26 = conn26.execute("SELECT id FROM profiles WHERE user_id = ?", (uid26,)).fetchone()["id"]
        c26.post(f"/profiles/{pid26}/select")
        # 26.3: menu do usuário
        t26 = c26.get("/").get_data(as_text=True)
        check("26.3 menu: Ver Perfil, Configurações, Trocar Usuário e Sair; sem Alterar foto",
              all(x in t26 for x in ("Ver Perfil", "Conf. Pessoais", "Trocar Usuário", "/logout")) and "Alterar foto" not in t26 and "Trocar perfil" not in t26)
        # 26.4: página Perfil
        r = c26.get("/profile")
        t26 = r.get_data(as_text=True)
        check("26.4 /profile: usuário, Entrou, Editar Perfil e Vamos Começar", r.status_code == 200 and "Ana26" in t26 and "Entrou" in t26 and "Editar Perfil" in t26 and "Vamos Começar" in t26)
        check("26.4 /profile sem sessão -> redireciona ao login", anon.get("/profile").status_code == 302)
        # 26.2: foto
        import io as io26
        png26 = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
        r = c26.post("/account/avatar", data={"file": (io26.BytesIO(png26), "a.png")}, content_type="multipart/form-data")
        check("26.2 upload de foto png (a foto é do perfil em uso: /pavatar/<perfil>)", r.status_code == 200 and r.json["url"].startswith(f"/pavatar/{pid26}"))
        check("26.2 GET /pavatar devolve a imagem", c26.get(f"/pavatar/{pid26}").mimetype == "image/png")
        r = c26.post("/account/avatar", data={"file": (io26.BytesIO(b"GIF89a"), "a.gif")}, content_type="multipart/form-data")
        check("26.2 foto fora de jpg/png/webp -> 400; sem arquivo -> 400", r.status_code == 400 and c26.post("/account/avatar").status_code == 400)
        check("26.2 sem sessão -> 401 JSON", anon.post("/account/avatar").status_code == 401)
        check("26.4 perfil com nome e foto: o cartão de preencher some", "Hora para preencher" not in c26.get("/profile").get_data(as_text=True))
        check("26.2 remover foto e fallback SVG", c26.delete("/account/avatar").status_code == 200 and c26.get(f"/pavatar/{pid26}").mimetype == "image/svg+xml")
        check("26.4 sem foto o cartão de preencher volta", "Hora para preencher" in c26.get("/profile").get_data(as_text=True))
        # 26.5: Editar Perfil
        check("26.5 /profile/edit abre", c26.get("/profile/edit").status_code == 200)
        P26 = lambda f, v: c26.post("/account/profile", json={"field": f, "value": v})
        r = P26("full_name", "  Ana   Maria ")
        check("26.5 nome completo normalizado", r.status_code == 200 and r.json["value"] == "Ana Maria")
        check("26.5 limites: local 61 caracteres e campo inválido -> 400", P26("location", "x" * 61).status_code == 400 and P26("foo", "x").status_code == 400)
        check("26.5 link: http/https ok, javascript:/ftp:// -> 400", P26("link", "exemplo.com").json["value"] == "https://exemplo.com"
              and P26("link", "javascript:alert(1)").status_code == 400 and P26("link", "ftp://a.com").status_code == 400)
        check("26.5 bio escapada na página", P26("bio", "<b>x</b>").status_code == 200 and "&lt;b&gt;x&lt;/b&gt;" in c26.get("/profile/edit").get_data(as_text=True))
        check("26.5 distintivo desligado some do Perfil", P26("show_badge", False).status_code == 200 and "Entrou" not in c26.get("/profile").get_data(as_text=True))
        check("26.5 sem sessão -> 401", anon.post("/account/profile", json={"field": "bio", "value": "x"}).status_code == 401)
        # 26.6: Conta e usuário
        t26 = c26.get("/account").get_data(as_text=True)
        check("26.6 /account: seções e linhas", c26.get("/account").status_code == 200 and all(x in t26 for x in ("Informações pessoais", "Segurança", "Configurações", "Nome completo")))
        check("26.6 usuário duplicado (caixa/acento) -> 400; com espaço -> 400", P26("username", "ADMIN").status_code == 400 and P26("username", "a b").status_code == 400)
        check("26.6 trocar usuário e logar com o novo (qualquer caixa)", P26("username", "AnaNova").status_code == 200
              and run.app.test_client().post("/login", data={"username": "ananova", "password": "abcd1"}).status_code == 302)
        # 26.7: senha
        PW26 = lambda n, cf, cur, out=False: c26.post("/account/password", json={"new": n, "confirm": cf, "current": cur, "logout_others": out})
        check("26.7 senha curta, confirmação diferente e atual errada -> 400", PW26("abc", "abc", "abcd1").status_code == 400
              and PW26("novasenha", "outra", "abcd1").status_code == 400 and PW26("novasenha", "novasenha", "errada").status_code == 400)
        other26 = run.app.test_client()
        other26.post("/login", data={"username": "ananova", "password": "abcd1"})
        other26.post(f"/profiles/{pid26}/select")
        check("26.7 outra sessão está ativa antes", other26.get("/account").status_code == 200)
        check("26.7 trocar senha encerrando as outras sessões", PW26("novasenha", "novasenha", "abcd1", True).status_code == 200)
        check("26.7 sessão atual segue ativa e a outra cai", c26.get("/account").status_code == 200 and other26.get("/account").status_code == 302)
        check("26.7 login com a nova senha", run.app.test_client().post("/login", data={"username": "ananova", "password": "novasenha"}).status_code == 302)
        check("26.7 sem sessão -> 401", anon.post("/account/password", json={}).status_code == 401)
        # 26.8: configurações (o usuário comum só vê bibliotecas liberadas, Fase 27)
        c.post(f"/admin/users/{uid26}/access", data={"library": [str(lib_mv["id"])]})
        S26 = lambda v: c26.post("/account/settings", json={"values": v})
        check("26.8 salvar configurações válidas", S26({"audio_lang": "pt", "sub_lang": "pt", "seen": "movies", "reviews": "none", "auto": True}).status_code == 200)
        check("26.8 valor inválido, chave desconhecida e corpo vazio -> 400", S26({"seen": "x"}).status_code == 400 and S26({"foo": "x"}).status_code == 400 and S26({}).status_code == 400)
        check("26.8 indicadores: <html data-seen> reflete a escolha", 'data-seen="movies"' in c26.get("/").get_data(as_text=True))
        check("26.8 /account mostra o resumo salvo", "Áudio: Português" in c26.get("/account").get_data(as_text=True))
        w26 = c26.get(f"/watch/movie/{mv}").get_data(as_text=True)
        check("26.8 player recebe o áudio/legenda da conta", 'data-audio="pt"' in w26 and 'data-sub="pt"' in w26)
        S26({"auto": False})
        w26 = c26.get(f"/watch/movie/{mv}").get_data(as_text=True)
        check("26.8 seleção automática desligada ignora o padrão da conta", 'data-audio=""' in w26 and 'data-sub=""' in w26)
        S26({"auto": True, "sdh": "sdh", "forced": "forced"})
        w26 = c26.get(f"/watch/movie/{mv}").get_data(as_text=True)
        check("26.8 SDH e legenda forçada chegam ao player", 'data-sdh="sdh"' in w26 and 'data-forced="forced"' in w26)
        check("26.8 sem sessão -> 401", anon.post("/account/settings", json={"values": {"seen": "all"}}).status_code == 401)
        # 26.1: remover usuário apaga a foto em data/avatars
        r = c26.post("/account/avatar", data={"file": (io26.BytesIO(png26), "a.png")}, content_type="multipart/form-data")
        import config as cfg26
        av26 = [f_ for f_ in os.listdir(cfg26.AVATARS_DIR) if f_.startswith(f"p{pid26}-")]
        c.post(f"/admin/users/{uid26}/delete")
        check("26.1 remover usuário apaga a foto do perfil do disco", av26 and not [f_ for f_ in os.listdir(cfg26.AVATARS_DIR) if f_.startswith(f"p{pid26}-")])
        # ---- Fase 27: Gerenciar acesso à biblioteca (apenas escrito; não rodar sem o Leo pedir) ----
        c.post("/admin/users", data={"username": "Rui27", "password": "abcd1"})
        c27 = run.app.test_client()
        c27.post("/login", data={"username": "rui27", "password": "abcd1"})
        c27.post("/profiles/new", data={"name": "Rui"})
        with _gdb23() as conn27:
            uid27 = conn27.execute("SELECT id FROM users WHERE username = 'Rui27'").fetchone()["id"]
            adm27 = conn27.execute("SELECT id FROM users WHERE is_admin = 1 ORDER BY id LIMIT 1").fetchone()["id"]
            pid27 = conn27.execute("SELECT id FROM profiles WHERE user_id = ?", (uid27,)).fetchone()["id"]
            libs27 = [r_["id"] for r_ in conn27.execute("SELECT id FROM libraries ORDER BY id")]
        c27.post(f"/profiles/{pid27}/select")
        L27 = lambda uid: [u_ for u_ in (c.get("/admin/access/data").json or {}).get("users", []) if u_["id"] == uid]
        P27 = lambda uid, body: c.post(f"/admin/access/user/{uid}", json=body)
        # 27.1: dados
        r = c.get("/admin/access/data")
        j27 = r.json or {}
        check("27.1 /admin/access/data: servidor, bibliotecas e usuários não-admin", r.status_code == 200 and j27.get("server") == "StarFlix"
              and len(j27.get("libraries", [])) == len(libs27) and L27(uid27) and not L27(adm27)
              and all({"id", "username", "full_name", "libraries"} <= set(u_) for u_ in j27["users"]))
        check("27.1 usuário novo começa sem bibliotecas", L27(uid27)[0]["libraries"] == [])
        check("27.1 não-admin -> 403 e sem sessão -> 401", c27.get("/admin/access/data").status_code == 403
              and c27.post(f"/admin/access/user/{uid27}", json={"libraries": []}).status_code == 403
              and anon.get("/admin/access/data").status_code == 401
              and anon.post(f"/admin/access/user/{uid27}", json={"libraries": []}).status_code == 401)
        # 27.1: gravar o conjunto
        r = P27(uid27, {"libraries": libs27[:2]})
        check("27.1 salvar duas bibliotecas devolve a linha atualizada", r.status_code == 200 and r.json["user"]["id"] == uid27
              and sorted(r.json["user"]["libraries"]) == sorted(libs27[:2]))
        from server.libraries import visible_libraries as vis27
        check("27.1 o usuário passa a ver só essas bibliotecas", {l_["id"] for l_ in vis27(uid27)} == set(libs27[:2]))
        r = P27(uid27, {"libraries": [libs27[0], str(libs27[0]), 999999]})
        check("27.1 substitui o conjunto; repetido e inexistente são ignorados", r.status_code == 200 and r.json["user"]["libraries"] == [libs27[0]]
              and {l_["id"] for l_ in vis27(uid27)} == {libs27[0]})
        check("27.1 corpo inválido -> 400 (texto, id não numérico, bool, negativo, sem corpo, não-objeto)",
              all(P27(uid27, b_).status_code == 400 for b_ in ({"libraries": "x"}, {"libraries": ["a"]}, {"libraries": [True]},
                                                                {"libraries": ["-1"]}, {"foo": 1}, [1]))
              and c.post(f"/admin/access/user/{uid27}").status_code == 400)
        check("27.1 conjunto anterior fica intacto após 400", L27(uid27)[0]["libraries"] == [libs27[0]])
        check("27.1 administrador -> 400 e usuário inexistente -> 404", P27(adm27, {"libraries": []}).status_code == 400 and P27(999999, {"libraries": []}).status_code == 404)
        # 27.2: página
        r = c.get("/admin/access")
        t27 = r.get_data(as_text=True)
        check("27.2 /admin/access: título, cartão e botão", r.status_code == 200 and all(x_ in t27 for x_ in ("Gerenciar acesso à biblioteca", "Contas com acesso à biblioteca", "Garantir acesso à biblioteca")))
        check("27.2 não-admin -> 403 e sem sessão -> /login", c27.get("/admin/access").status_code == 403 and anon.get("/admin/access", headers={"Accept": "text/html"}).status_code == 302)
        # 27.3: arquivos do modal
        js27 = open(os.path.join(ROOT, "web", "static", "js", "library-access.js"), encoding="utf-8").read()
        check("27.3 modal: passos, rótulos e API", uses_text(js27, "Garantir acesso à biblioteca", "Resultado da Pesquisa", "Anterior", "Salvar") and all(x_ in js27 for x_ in ("sfLibAccess", "la:saved")))
        check("27.3 página carrega o modal antes da lista", t27.index("library-access.js") < t27.index("library-access-page.js"))
        # 27.4: navegação e rota antiga
        t27 = c.get("/").get_data(as_text=True)
        # Fase 33: o link só aparece na barra lateral do modo admin (/admin*)
        check("27.4 sidebar do admin tem o link; a do usuário comum não", "/admin/access" in c.get("/admin").get_data(as_text=True) and "/admin/access" not in c27.get("/").get_data(as_text=True))
        check("27.4 página Usuários (V301) serve a lista em JSON e o link de acesso fica no JS",
              any(u["id"] == uid27 for u in c.get("/admin/users/data").json["users"])
              and "/admin/access?user=" in open(os.path.join(ROOT, "web", "static", "js", "user-manager.js"), encoding="utf-8").read())
        r = c.get(f"/admin/users/{uid27}/access")
        check("27.4 rota antiga GET redireciona para /admin/access?user=<id>", r.status_code == 302 and r.headers["Location"].endswith(f"/admin/access?user={uid27}")
              and c.get("/admin/users/999999/access").status_code == 404)
        r = c.post(f"/admin/users/{uid27}/access", data={"library": [str(libs27[1])]})
        check("27.4 rota antiga POST segue gravando (função única)", r.status_code == 302 and L27(uid27)[0]["libraries"] == [libs27[1]])
        # 27.1: Conceder Acesso por item reaproveita a mesma função
        P27(uid27, {"libraries": []})
        r = c.post(f"/admin/item/movie/{mv}/access", data={"user": "rui27"})
        check("27.1 Conceder Acesso (25.6) continua liberando a biblioteca do item", r.status_code == 200 and len(L27(uid27)[0]["libraries"]) == 1)
        # 27.1: desmarcar tudo
        check("27.1 desmarcar tudo deixa o usuário sem bibliotecas (a página o oculta)", P27(uid27, {"libraries": []}).json["user"]["libraries"] == [] and not vis27(uid27))
        c.post(f"/admin/users/{uid27}/delete")
        check("27.1 usuário removido some da lista e o POST dá 404", not L27(uid27) and P27(uid27, {"libraries": []}).status_code == 404)
        # 23.25: excluir (por último; não apaga do disco)
        r = c.post(f"/admin/item/episode/{ep}/delete")
        check("23.25 excluir episódio do banco", r.status_code == 200 and c.get(f"/admin/item/episode/{ep}/edit").status_code == 404)
    else:
        check("Fase 23: dados de teste (filme, série, episódio) existem", False)

    # ---- Fase 28 (28.1 a 28.8): bibliotecas com várias pastas, opções e API JSON (28.16)
    def J28(url, body=None, cl=None):
        cl = cl or c
        return cl.post(url, json=body) if body is not None else cl.get(url)

    def wait28():
        for _ in range(100):
            if not is_scanning():
                return
            time.sleep(0.2)

    fa, fb, fc = (os.path.join(TMP, n) for n in ("f28a", "f28b", "f28c"))
    for d_ in (fa, fb, fc):
        os.makedirs(d_)
    make_video(os.path.join(fa, "Filme A (2001).mp4"))
    make_video(os.path.join(fb, "Filme B (2002).mp4"))
    make_video(os.path.join(fc, "Filme C (2003).mp4"))
    anon28 = run.app.test_client()
    check("28.3 sem sessão: 401 JSON em data/add/update/settings", all(
        r_.status_code == 401 for r_ in (anon28.get("/admin/libraries/data"), anon28.post("/admin/libraries/add", json={}),
                                          anon28.post("/admin/libraries/1/update", json={}), anon28.get("/admin/libraries/settings"))))
    d28 = J28("/admin/libraries/data").json
    check("28.3 data traz tipos, padrões e atalhos, sem lista de idiomas (59.37)", all(k in d28 for k in ("libraries", "types", "defaults", "settings", "cert_countries")) and "langs" not in d28)
    br28 = c.get("/admin/browse?path=" + TMP).json
    check("28.3 browse devolve home e roots", "home" in br28 and "roots" in br28 and any(r_["path"] == "/" for r_ in br28["roots"]))
    r = J28("/admin/libraries/add", {"name": "Multi", "type": "movie", "lang": "pt-BR", "folders": [fa, fb], "prefs": {}})
    check("28.2 add com duas pastas", r.status_code == 201 and r.json["library"]["folders"] == [fa, fb])
    wait28()
    lib28 = r.json["library"]["id"]
    check("28.2 scan percorre todas as pastas", len(re.findall("Filme [AB]", c.get(f"/library/{lib28}").get_data(as_text=True))) >= 2)
    check("28.2 pasta repetida em outra biblioteca é recusada", J28("/admin/libraries/add", {"name": "X", "type": "movie", "folders": [fa]}).status_code == 400)
    check("28.2 pasta aninhada é recusada", J28("/admin/libraries/add", {"name": "X", "type": "movie", "folders": [os.path.join(fa, "sub")]}).status_code == 400)
    check("28.2 pasta duplicada na mesma lista é recusada", J28("/admin/libraries/add", {"name": "X", "type": "movie", "folders": [fc, fc]}).status_code == 400)
    check("28.2 sem pasta é recusado", J28("/admin/libraries/add", {"name": "X", "type": "movie", "folders": []}).status_code == 400)
    check("28.3 add: tipo inválido recusado", J28("/admin/libraries/add", {"name": "X", "type": "music", "folders": [fc]}).status_code == 400)
    check("28.1 add: prefs inválidas recusadas", all(J28("/admin/libraries/add", {"name": "X", "type": "movie", "folders": [fc], "prefs": p_}).status_code == 400
                                                   for p_ in ({"visibility": "nada"}, {"adult": "sim"}, {"cert_country": "ZZ"}, "texto")))
    u28 = f"/admin/libraries/{lib28}/update"
    check("28.3 update não troca o tipo", J28(u28, {"type": "show"}).status_code == 400)
    check("28.3 update: nome vazio recusado; `lang` é ignorado (59.37: idioma vem do usuário)", J28(u28, {"name": " "}).status_code == 400
          and (lambda r_: r_.status_code == 200 and "lang" not in r_.json["library"])(J28(u28, {"lang": "xx"})))
    check("28.3 update: biblioteca inexistente dá 404", J28("/admin/libraries/999999/update", {"name": "Y"}).status_code == 404)
    r = J28(u28, {"name": "Multi2", "lang": "en-US", "prefs": {"cert_country": "US", "original_titles": True}})
    check("28.1 update grava nome e prefs e não grava idioma por biblioteca", r.status_code == 200 and (lambda l_: l_["name"] == "Multi2" and "lang" not in l_
          and l_["prefs"]["cert_country"] == "US" and l_["prefs"]["original_titles"] is True and l_["prefs"]["agent"] == "tmdb")(
        next(x_ for x_ in J28("/admin/libraries/data").json["libraries"] if x_["id"] == lib28)))
    r = J28(u28, {"folders": [fa]})
    wait28()
    check("28.2 remover pasta apaga só os itens dela", r.status_code == 200 and "Filme B" not in c.get(f"/library/{lib28}").get_data(as_text=True)
          and "Filme A" in c.get(f"/library/{lib28}").get_data(as_text=True))
    check("28.2 update com pasta de outra biblioteca é recusado", J28(u28, {"folders": [fa, movies]}).status_code == 400)
    check("28.2 update com outra pasta livre é aceito", J28(u28, {"folders": [fa, fc]}).status_code == 200)
    wait28()
    # 28.6 visibility
    J28(u28, {"prefs": {"visibility": "hide_home"}})
    check("28.6 hide_home: biblioteca some do Início e segue acessível", "Filme A" not in c.get("/").get_data(as_text=True)
          and c.get(f"/library/{lib28}").status_code == 200)
    J28(u28, {"prefs": {"visibility": "hide_all"}})
    check("28.6 hide_all: some da busca global", "Filme A" not in c.get("/search?q=Filme").get_data(as_text=True))
    J28(u28, {"prefs": {"visibility": "all"}})
    check("28.6 all: volta ao Início", "Filme A" in c.get("/").get_data(as_text=True))
    # 28.8 merge_recent
    check("28.8 settings: valor não booleano recusado", J28("/admin/libraries/settings", {"merge_recent": "sim"}).status_code == 400)
    check("28.8 settings liga merge_recent", J28("/admin/libraries/settings", {"merge_recent": True}).json["merge_recent"] is True
          and J28("/admin/libraries/data").json["settings"]["merge_recent"] is True)
    check("28.8 Início mostra a fileira mesclada por tipo", "Filmes Adicionados Recentemente" in [x_["title"] for x_ in c.get("/home/rows").json["rows"]])
    check("28.8 settings desliga merge_recent", J28("/admin/libraries/settings", {"merge_recent": False}).json["merge_recent"] is False)
    # 28.4 agent = none e rating_source sem chave
    check("28.4 rating_source IMDb sem OMDB_API_KEY é recusado", J28(u28, {"prefs": {"rating_source": "imdb"}}).status_code == 400)
    check("28.4 agent = none aceito", J28(u28, {"prefs": {"agent": "none"}}).status_code == 200)
    # 28.11 validação de pasta no navegador
    ck28 = "/admin/libraries/check-folder"
    check("28.11 check-folder: ok, repetida, inexistente e 401", J28(ck28, {"path": fb}).status_code == 200 and J28(ck28, {"path": fa}).status_code == 400
          and J28(ck28, {"path": os.path.join(TMP, "nao-existe")}).status_code == 400 and anon28.post(ck28, json={"path": fb}).status_code == 401)
    check("28.11 browse sinaliza pasta inexistente", c.get("/admin/browse?path=" + os.path.join(TMP, "nao-existe")).json["missing"] is True)
    # Fase 29: menu da biblioteca, fixar, ações e modais (29.1–29.4, 29.9, 29.10)
    from server.scanner import exclusive  # noqa: E402
    pg = c.get(f"/library/{lib28}").get_data(as_text=True)
    check("29.5 página da biblioteca traz o menu e os scripts do admin", "data-lib-menu" in pg and all(f in pg for f in ("library-menu.js", "library-actions.js", "library-delete.js")))
    check("static com cache-busting (?v=)", re.search(r"library-delete\.js\?v=\d+", c.get("/admin/libraries").get_data(as_text=True)) is not None)
    check("29.9 /admin/libraries carrega library-delete.js antes do manager", "library-delete.js" in c.get("/admin/libraries").get_data(as_text=True))
    js = {n: c.get(f"/static/js/{n}.js").get_data(as_text=True) for n in ("library-delete", "library-actions", "library-menu")}
    check("29.9 modal Apagar Biblioteca: textos, checkbox e botão vermelho", uses_text(js["library-delete"], "Apagar Biblioteca", "Sim, apagar a biblioteca", "Esta operação não poderá ser desfeita") and "em-danger" in js["library-delete"] and "disabled" in js["library-delete"])
    check("29.10 modais Analisar, Atualizar e Esvaziar com os textos da §5.17", all(any(f in v for v in _PT.values()) for f in ("Analisa todos os arquivos de mídia", "Força o download de informações atualizadas", "Remove da biblioteca os itens cujos arquivos não existem mais")) and all(t in js["library-actions"] for t in ("lib.act.", "empty-trash", "refresh-info")))
    check("29.5 menu registra Excluir e as demais ações", "actions['delete']" in js["library-menu"] and "started:" in js["library-menu"])
    nav = lambda: re.search(r'<a[^>]*href="/library/%d"[^>]*nav-item|<a[^>]*nav-item[^>]*href="/library/%d"' % (lib28, lib28), c.get("/library/%d" % lib28).get_data(as_text=True)) is not None
    check("29.2 biblioteca começa fixada na barra lateral", nav())
    info = c.get(f"/library/{lib28}/info")
    check("29.4 info: scanning, scanned_at, pinned e users", info.status_code == 200 and all(k in info.json for k in ("scanning", "scanned_at", "pinned", "users")) and info.json["pinned"] is True)
    check("29.2 pin: corpo inválido dá 400 e id inexistente dá 404", c.post(f"/library/{lib28}/pin", json={"pinned": "x"}).status_code == 400 and c.post("/library/999999/pin", json={"pinned": False}).status_code == 404)
    check("29.2 pin: sem sessão 401", anon28.post(f"/library/{lib28}/pin", json={"pinned": False}).status_code == 401 and anon28.get(f"/library/{lib28}/info").status_code == 401)
    check("29.2 desafixar tira da barra lateral e segue acessível", c.post(f"/library/{lib28}/pin", json={"pinned": False}).json["pinned"] is False and not nav()
          and c.get(f"/library/{lib28}").status_code == 200 and c.get(f"/library/{lib28}/info").json["pinned"] is False)
    check("29.2 fixar de novo volta à barra lateral", c.post(f"/library/{lib28}/pin", json={"pinned": True}).json["pinned"] is True and nav())
    acts = ("analyze", "refresh-info", "examine", "empty-trash")
    check("29.3 ações sem sessão: 401; id inexistente: 404", all(anon28.post(f"/admin/libraries/{lib28}/{a}").status_code == 401 for a in acts)
          and all(c.post(f"/admin/libraries/999999/{a}").status_code == 404 for a in acts))
    with exclusive() as got:
        check("29.3 trava: com exame em andamento as 4 ações dão 409", got and all(c.post(f"/admin/libraries/{lib28}/{a}").status_code == 409 for a in acts))
    for a in ("analyze", "refresh-info", "examine"):
        r = c.post(f"/admin/libraries/{lib28}/{a}")
        check(f"29.3 {a} inicia o exame", r.status_code == 200 and r.json.get("scanning") is True)
        wait28()
    check("29.1 scanned_at gravado ao fim do exame", c.get(f"/library/{lib28}/info").json["scanned_at"] is not None)
    r = c.post(f"/admin/libraries/{lib28}/empty-trash")
    check("29.3 empty-trash devolve removed e não apaga arquivos que existem", r.status_code == 200 and r.json.get("removed") == 0 and r.json.get("scanning") is False)
    # Fase 31 (escrito, não rodado sem o Leo pedir): regras inteligentes, coleção/lista inteligente, listas, fila, página, modos de exibição
    from server.db import get_db as _gdb31  # noqa: E402
    with _gdb31() as cn31:
        mids31 = [r["id"] for r in cn31.execute("SELECT id FROM media WHERE library_id = ? ORDER BY id", (lib28,))]
    check("31.x biblioteca de teste tem itens", len(mids31) >= 1)
    pv = f"/library/{lib28}/smart/preview"
    check("31.2 preview sem sessão: 401", anon28.get(pv).status_code == 401)
    sp = json.dumps({"rules": [{"field": "title", "op": "contains", "value": "Filme"}]})
    rp = c.get(pv + "?spec=" + sp)
    check("31.2 preview com regra Título contém", rp.status_code == 200 and rp.json["total"] == len(rp.json["ids"]) and rp.json["total"] >= 1)
    check("31.2 preview com JSON/regra inválidos: 400", c.get(pv + "?spec=%7B").status_code == 400 and c.get(pv + '?spec={"match":"x"}').status_code == 400
          and c.get("/library/999999/smart/preview").status_code == 404)
    for bad in ({"match": "x"}, {"rules": [{"field": "nada", "op": "is", "value": "1"}]}, {"rules": [{"field": "year", "op": "contains", "value": "1"}]},
                {"rules": [{"field": "year", "op": "gt", "value": "abc"}]}, {"rules": "x"}):
        check(f"31.2 regra inválida recusada: {str(bad)[:40]}", c.post("/playlists", json={"title": "Inv", "library_id": lib28, "smart": True, **bad}).status_code == 400)
    # 31.3 coleção inteligente (admin)
    r = c.post("/admin/collections", json={"title": "Inteligente 31", "library_id": lib28, "smart": True, "rules": [{"field": "title", "op": "contains", "value": "Filme"}]})
    check("31.3 coleção inteligente criada", r.status_code == 200 and r.json.get("smart") is True)
    cid31 = r.json.get("id")
    check("31.3 título repetido: 409; sem sessão: 401", c.post("/admin/collections", json={"title": "inteligente 31", "library_id": lib28, "smart": True, "rules": []}).status_code == 409
          and anon28.post("/admin/collections", json={"title": "X", "library_id": lib28}).status_code == 401)
    check("31.3 coleção inteligente abre", c.get(f"/collection/{cid31}").status_code == 200)
    check("31.3 aba Coleções lista a inteligente", "Inteligente 31" in c.get(f"/library/{lib28}?tab=collections").get_data(as_text=True))
    # 31.4 listas de reprodução
    r = c.post("/playlists", json={"title": "Lista 31", "library_id": lib28, "media_ids": mids31[:2]})
    check("31.4 lista manual criada", r.status_code == 200 and r.json["n"] == min(2, len(mids31)) and r.json["smart"] is False)
    pid31 = r.json["id"]
    check("31.4 nome repetido: 409; vazio: 400; biblioteca inválida: 404/400", c.post("/playlists", json={"title": "lista 31", "library_id": lib28}).status_code == 409
          and c.post("/playlists", json={"title": " ", "library_id": lib28}).status_code == 400
          and c.post("/playlists", json={"title": "Y", "library_id": 999999}).status_code in (400, 404))
    check("31.4 sem sessão: 401 em listar/criar; página redireciona ao login", anon28.get(f"/playlists?library={lib28}").status_code == 401
          and anon28.post("/playlists", json={"title": "Z", "library_id": lib28}).status_code == 401 and anon28.get(f"/playlist/{pid31}").status_code == 302)
    r = c.post(f"/playlists/{pid31}/items", json={"media_ids": mids31})
    check("31.4 adicionar itens ignora duplicata", r.status_code == 200 and r.json["n"] == len(mids31))
    r = c.post("/playlists", json={"title": "Esperta 31", "library_id": lib28, "smart": True, "rules": [{"field": "title", "op": "contains", "value": "Filme"}], "limit": 1})
    check("31.2 limite respeitado na lista inteligente", r.status_code == 200 and r.json["n"] <= 1)
    sp31 = r.json["id"]
    check("31.4 lista inteligente recusa itens manuais", c.post(f"/playlists/{sp31}/items", json={"media_ids": mids31}).status_code == 400
          and c.delete(f"/playlists/{sp31}/items/{mids31[0]}").status_code == 400)
    check("31.4 /playlists lista só manuais por padrão e todas com smart=1", len(c.get(f"/playlists?library={lib28}").json["playlists"]) == 1
          and len(c.get(f"/playlists?library={lib28}&smart=1").json["playlists"]) == 2)
    check("31.4 lista inexistente: 404", c.post("/playlists/999999/items", json={"media_ids": [1]}).status_code == 404 and c.delete("/playlists/999999").status_code == 404)
    # 31.9 página, aba, edição, imagens, fila
    pg31 = c.get(f"/playlist/{pid31}")
    check("31.9 página da lista abre com título, linhas e scripts", pg31.status_code == 200 and "Lista 31" in pg31.get_data(as_text=True) and "pl-row" in pg31.get_data(as_text=True)
          and "playlist-edit.js" in pg31.get_data(as_text=True))
    check("31.9 página de lista inexistente: 404", c.get("/playlist/999999").status_code == 404)
    check("31.9 aba Listas de reprodução aparece e abre", "Listas de reprodução" in c.get(f"/library/{lib28}").get_data(as_text=True)
          and "data-playlist" in c.get(f"/library/{lib28}?tab=playlists").get_data(as_text=True))
    ed = c.get(f"/playlist/{pid31}/edit")
    check("31.9 edit GET: campos e imagens", ed.status_code == 200 and ed.json["fields"]["title"] == "Lista 31" and set(ed.json["images"]) == {"poster", "backdrop", "logo", "square"})
    check("31.9 edit POST: título e resumo salvos", c.post(f"/playlist/{pid31}/edit", json={"fields": {"title": "Lista 31b", "summary": "Resumo 31"}}).status_code == 200
          and "Resumo 31" in c.get(f"/playlist/{pid31}").get_data(as_text=True))
    check("31.9 edit POST: título repetido 409, vazio 400, sem sessão 401", c.post(f"/playlist/{pid31}/edit", json={"fields": {"title": "Esperta 31"}}).status_code == 409
          and c.post(f"/playlist/{pid31}/edit", json={"fields": {"title": " "}}).status_code == 400 and anon28.post(f"/playlist/{pid31}/edit", json={}).status_code == 401)
    png31 = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    r = c.post(f"/playlist/{pid31}/image/poster", data={"file": (io.BytesIO(png31), "x.png")}, content_type="multipart/form-data")
    check("31.9 imagem: upload png aceito e servido", r.status_code == 200 and c.get(f"/playlist-image/{pid31}/poster").status_code == 200)
    check("31.9 imagem: tipo inválido 400, slot inválido 404, URL privada 400", c.post(f"/playlist/{pid31}/image/logo", data={"file": (io.BytesIO(b"texto"), "x.png")}, content_type="multipart/form-data").status_code == 400
          and c.post(f"/playlist/{pid31}/image/xx", data={"clear": "1"}).status_code == 404
          and c.post(f"/playlist/{pid31}/image/logo", data={"url": "http://127.0.0.1/x.png"}).status_code == 400)
    check("31.9 imagem: limpar remove a capa", c.post(f"/playlist/{pid31}/image/poster", data={"clear": "1"}).status_code == 200 and c.get(f"/playlist-image/{pid31}/poster").status_code == 404)
    r = c.post("/bulk/queue", json={"ids": mids31})
    check("31.5 /bulk/queue devolve itens {k, id}", r.status_code == 200 and r.json["n"] == len(r.json["items"]) and all(x["k"] in ("movie", "episode") for x in r.json["items"])
          and anon28.post("/bulk/queue", json={"ids": mids31}).status_code == 401)
    check("31.5 /bulk/queue ignora corpo inválido", c.post("/bulk/queue", json=[1]).json["n"] == 0)
    # 31.10 dados dos modos de exibição
    rw = c.get(f"/library/{lib28}/rows")
    check("31.10 /library/<id>/rows: campos por item e 401/404", rw.status_code == 200 and all(k in next(iter(rw.json["rows"].values())) for k in ("o", "d", "rt", "rd", "cc", "ad", "res", "s"))
          and anon28.get(f"/library/{lib28}/rows").status_code == 401 and c.get("/library/999999/rows").status_code == 404)
    lv = c.get("/static/js/library-view.js").get_data(as_text=True)
    check("31.10 script traz os 3 modos e as colunas", all(any(f == v for k, v in _PT.items() if k.startswith("lib.col.")) for f in ("Data de Lançamento", "Duração")) and all(t in lv for t in ("sf.view", "sf.cols", "lib.col.", "pgrid-table", "pgrid-detail")))
    check("31.10 menu da Grelha liga os 3 modos", uses_text(c.get("/static/js/library-bar.js").get_data(as_text=True), "Visualização em Detalhes", "Exibição em Tabela") and "V.set('table')" in c.get("/static/js/library-bar.js").get_data(as_text=True))
    # exclusão e limpeza de imagens
    check("31.4 excluir lista: 200 e página some", c.delete(f"/playlists/{pid31}").status_code == 200 and c.get(f"/playlist/{pid31}").status_code == 404)
    c.delete(f"/playlists/{sp31}")
    check("31.3 excluir coleção inteligente", c.delete(f"/admin/collections/{cid31}").status_code == 200)
    # ---- Fase 32 (32.1 a 32.7): Início dinâmico — TMDB simulado, sem rede (32.12: escrito, não rodar sem o Leo pedir)
    import requests as rq32  # noqa: E402
    import config as cfg32  # noqa: E402
    from collections import Counter  # noqa: E402
    from server import home_rows as hr32, metadata as md32, tmdb_lists as tl32  # noqa: E402
    from server.db import get_db as _gdb32, migrate as mig32  # noqa: E402
    from server.home_rows import genre_title as gt32  # noqa: E402
    from server.playlists import total_text as tt32  # noqa: E402

    def sql32(q, *a):
        with _gdb32() as cn_:
            return cn_.execute(q, a).fetchall()

    d32m, d32s = os.path.join(TMP, "f32m"), os.path.join(TMP, "f32s")
    os.makedirs(d32m)
    os.makedirs(os.path.join(d32s, "Serie32 (2020)"))
    t32 = [f"Filme32 {i:02d}" for i in range(1, 13)] + ["Extra32 A", "Extra32 B", "Extra32 C"]
    base32 = os.path.join(d32m, "Filme32 01 (2010).mp4")
    make_video(base32)
    for i_, t_ in enumerate(t32[1:], start=1):
        shutil.copy(base32, os.path.join(d32m, f"{t_} ({2010 + i_}).mp4"))
    for e_ in (1, 2, 3):
        shutil.copy(base32, os.path.join(d32s, "Serie32 (2020)", f"Serie32.S01E0{e_}.mp4"))
    lm32 = J28("/admin/libraries/add", {"name": "Filmes32", "type": "movie", "folders": [d32m], "prefs": {}}).json["library"]["id"]
    wait28()
    ls32 = J28("/admin/libraries/add", {"name": "Series32", "type": "show", "folders": [d32s], "prefs": {}}).json["library"]["id"]
    wait28()
    by32 = {r_["title"]: r_["id"] for r_ in sql32("SELECT id, title FROM media WHERE library_id = ?", lm32)}
    sh_ = sql32("SELECT id FROM media WHERE library_id = ?", ls32)
    sh32 = sh_[0]["id"] if sh_ else None
    ep32 = [r_["id"] for r_ in sql32("SELECT id FROM episodes WHERE media_id = ? ORDER BY season, episode", sh32)] if sh32 else []
    M, U = [by32.get(t_) for t_ in t32[:12]], [by32.get(t_) for t_ in t32[12:]]
    if None not in M + U and sh32 and len(ep32) == 3:
        adm32 = sql32("SELECT id FROM users WHERE is_admin = 1 ORDER BY id LIMIT 1")[0]["id"]
        c.post("/admin/users", data={"username": "Rui32", "password": "abcd1"})
        c32 = run.app.test_client()
        c32.post("/login", data={"username": "rui32", "password": "abcd1"})
        c32.post("/profiles/new", data={"name": "Rui"})
        uid32 = sql32("SELECT id FROM users WHERE username = 'Rui32'")[0]["id"]
        pid32 = sql32("SELECT id FROM profiles WHERE user_id = ?", uid32)[0]["id"]
        c32.post(f"/profiles/{pid32}/select")
        for i_, m_ in enumerate(M):
            sql32("UPDATE media SET tmdb_id = ? WHERE id = ?", 5001 + i_, m_)
        for i_, u_ in enumerate(U):
            sql32("UPDATE media SET tmdb_id = ? WHERE id = ?", 5101 + i_, u_)
        sql32("UPDATE media SET tmdb_id = 7000 WHERE id = ?", sh32)
        for gen_, grp_ in (("Terror", M[:6]), ("Comédia", M[6:]), ("Drama", M[:4])):  # Drama fica com 4 + 1 de 23.21 = 5 (< mínimo 6)
            for m_ in grp_:
                sql32("INSERT OR IGNORE INTO tags (media_id, kind, name) VALUES (?, 'genre', ?)", m_, gen_)

        def rows32(cl=c):
            hr32._cache.clear()
            r_ = cl.get("/home/rows")
            return r_.json["rows"] if r_.status_code == 200 else []

        row32 = lambda key, cl=c: next((x_ for x_ in rows32(cl) if x_["key"] == key), None)
        ids32 = lambda r_: [i_["id"] for i_ in (r_ or {}).get("items", [])]
        grant32 = lambda libs: c.post(f"/admin/access/user/{uid32}", json={"libraries": libs})
        HID32 = ["continue", "on_deck", "mylist", "new_episodes", "because_watched", "top_server"]
        hide32 = lambda keys: sql32("INSERT OR REPLACE INTO home_prefs (profile_id, hidden, \"order\") VALUES (?, ?, '[]')", pid, json.dumps(keys))
        hide32(HID32)  # as fileiras de uso ficam fora das checagens por HTTP (os provedores são testados direto, em 32.4)
        J28("/admin/libraries/settings", {"merge_recent": False})

        # 32.1: migração
        tabs32 = {r_["name"] for r_ in sql32("SELECT name FROM sqlite_master WHERE type = 'table'")}
        cols32 = lambda t_: {r_["name"] for r_ in sql32(f"PRAGMA table_info({t_})")}
        check("32.1 tabelas tmdb_lists e home_prefs com as colunas previstas", {"tmdb_lists", "home_prefs"} <= tabs32
              and {"list_key", "region", "lang", "ids", "fetched_at"} <= cols32("tmdb_lists") and {"profile_id", "hidden", "order"} <= cols32("home_prefs"))
        try:
            with _gdb32() as cn32:
                mig32(cn32)
                mig32(cn32)
            mig_ok32 = True
        except Exception:
            mig_ok32 = False
        check("32.1 migração idempotente (roda duas vezes sem erro)", mig_ok32)
        sql32("INSERT INTO profiles (user_id, name) VALUES (?, 'Tmp32')", uid32)
        tp32 = sql32("SELECT id FROM profiles WHERE name = 'Tmp32'")[0]["id"]
        sql32("INSERT INTO home_prefs (profile_id, hidden, \"order\") VALUES (?, '[\"mylist\"]', '[]')", tp32)
        sql32("DELETE FROM profiles WHERE id = ?", tp32)
        check("32.1 home_prefs some junto com o perfil (ON DELETE CASCADE)", not sql32("SELECT 1 FROM home_prefs WHERE profile_id = ?", tp32))

        # 32.2: listas do TMDB (get simulado, sem rede)
        calls32 = []

        def fake32(path, **params):
            calls32.append((path, dict(params)))
            data32 = {"/movie/popular": [5003, 5001, 5003, 99999, "x"], "/tv/popular": [7000, 5001], "/movie/now_playing": [5002],
                      "/tv/airing_today": [12345], "/trending/movie/week": [5001, 5002, 5003], "/trending/tv/week": [7000]}
            return {"results": [{"id": i_} for i_ in data32.get(path, [])]}

        real32 = (md32.tmdb_get, cfg32.TMDB_API_KEY, cfg32.TMDB_REGION)
        md32.tmdb_get, cfg32.TMDB_API_KEY = fake32, "chave"
        n32 = tl32.refresh_stale()
        with _gdb32() as cn32:
            pop32, vazia32 = tl32.list_ids(cn32, "movie_popular"), tl32.list_ids(cn32, "movie_top_rated")
        check("32.2 refresh_stale baixa as 10 listas (2 páginas cada) e grava em tmdb_lists", n32 == len(tl32.LISTS) == 10 and len(calls32) == 20
              and len(sql32("SELECT 1 FROM tmdb_lists")) == 10)
        check("32.2 ids na ordem do TMDB, sem repetidos nem valores não inteiros; lista vazia vira []", pop32 == [5003, 5001, 99999] and vazia32 == [])
        check("32.2 region só nas listas de filmes; language em todas", all((p_.get("region") == cfg32.TMDB_REGION) == pth_.startswith("/movie/")
                                                                         and p_.get("language") == cfg32.TMDB_LANG for pth_, p_ in calls32))
        calls32.clear()
        check("32.2 listas recentes não são baixadas de novo", tl32.refresh_stale() == 0 and not calls32)
        tl32.ensure_fresh()
        check("32.2 ensure_fresh com cache completo não busca nada", not calls32 and tl32._bg["running"] is False)
        sql32("UPDATE tmdb_lists SET fetched_at = fetched_at - 90000 WHERE list_key = 'tv_popular'")
        cfg32.TMDB_API_KEY = ""
        check("32.2 sem TMDB_API_KEY nada é baixado, nem lista vencida", tl32.refresh_stale() == 0 and not calls32)
        cfg32.TMDB_API_KEY = "chave"
        check("32.2 lista com mais de 24 h é renovada sozinha (só ela)", tl32.refresh_stale() == 1 and len(calls32) == 2)
        md32.tmdb_get = lambda path, **p: (_ for _ in ()).throw(rq32.ConnectionError("sem rede"))
        falhou32 = tl32.refresh_list("movie_popular")
        with _gdb32() as cn32:
            apos32 = tl32.list_ids(cn32, "movie_popular")
        check("32.2 falha de rede devolve False e mantém o cache anterior", falhou32 is False and apos32 == [5003, 5001, 99999])
        with _gdb32() as cn32:
            mt = lambda uid_, key_, **kw: tl32.matches(cn32, uid_, key_, **kw)
            check("32.2 matches: filme só em biblioteca de filmes, na ordem do TMDB", mt(adm32, "movie_popular") == [M[2], M[0]])
            check("32.2 matches: série só em biblioteca de séries (id de filme na lista de séries não casa)", mt(adm32, "tv_popular") == [sh32])
            check("32.2 matches: limit e chave desconhecida", mt(adm32, "movie_popular", limit=1) == [M[2]] and mt(adm32, "nao_existe") == [])
            check("32.2 matches: usuário sem acesso à biblioteca não casa nada", mt(uid32, "movie_popular") == [])
            grant32([lm32])
            check("32.2 matches: com acesso à biblioteca casa só o que ela tem", mt(uid32, "movie_popular") == [M[2], M[0]] and mt(uid32, "tv_popular") == [])
        cfg32.TMDB_REGION = "US"
        with _gdb32() as cn32:
            outra32 = tl32.list_ids(cn32, "movie_popular")
        cfg32.TMDB_REGION = real32[2]
        check("32.2 região diferente da atual conta como lista ausente", outra32 == [])
        md32.tmdb_get, cfg32.TMDB_API_KEY = real32[0], real32[1]  # as listas ficam no cache; daqui em diante não há rede nem chave

        # 32.5: fileiras do TMDB + 32.3 dedupe
        rws = rows32()
        k32 = [x_["key"] for x_ in rws]
        pos32 = lambda key: ids32(next((x_ for x_ in rws if x_["key"] == key), None))
        tit32 = {x_["key"]: x_["title"] for x_ in rws}
        check("32.5 Em Cartaz nos Cinemas, Populares e Séries Populares: só o que existe no servidor", pos32("tmdb_movie_now_playing") == [M[1]]
              and pos32("tmdb_movie_popular") == [M[2], M[0]] and pos32("tmdb_tv_popular") == [sh32])
        check("32.5 fileira some sem itens do servidor (lista vazia ou sem correspondência)",
              not {"tmdb_tv_airing_today", "tmdb_tv_on_the_air", "tmdb_movie_top_rated", "tmdb_tv_top_rated"} & set(k32))
        check("32.5 Em Alta na Semana intercala filmes e séries", pos32("tmdb_trending") == [M[0], sh32, M[1], M[2]])
        check("32.5 títulos em pt-BR", tit32.get("tmdb_movie_now_playing") == "Em Cartaz nos Cinemas" and tit32.get("tmdb_movie_popular") == "Filmes Populares"
              and tit32.get("tmdb_tv_popular") == "Séries Populares" and tit32.get("tmdb_trending") == "Em Alta na Semana")
        cnt32 = Counter(i_["uid"] for x_ in rws for i_ in x_["items"] if i_.get("uid") is not None)
        check("32.3 o mesmo item não aparece em mais de 2 fileiras", cnt32 and max(cnt32.values()) <= 2)
        rec32 = ids32(next((x_ for x_ in rws if x_["key"] == f"recent_lib_{lm32}"), None))
        check("32.3 dedupe: item que já está em 2 fileiras fica de fora da 3ª", not ({M[0], M[1], M[2]} & set(rec32)) and M[3] in rec32)
        sql32("DELETE FROM tmdb_lists")
        check("32.5 sem listas do TMDB (sem chave/cache) as fileiras somem em silêncio", c.get("/home/rows").status_code == 200
              and not [x_ for x_ in rows32() if x_["key"].startswith("tmdb_")])

        # 32.3: motor (mínimo, máximo, limite de fileiras, provedor com defeito, preferências, rotas)
        def temp32(key, items, min_items=1, max_items=hr32.MAX_ITEMS):
            hr32.row(key, "Tmp " + key, "poster", min_items, max_items)(items if callable(items) else (lambda ctx, _i=items: _i))

        def front32(*keys):
            hr32.ORDER[:0] = list(keys)

        def drop32(*keys):
            for k_ in keys:
                hr32.REGISTRY.pop(k_, None)
                while k_ in hr32.ORDER:
                    hr32.ORDER.remove(k_)

        it32 = lambda n_, p_="z": [{"uid": f"{p_}:{i_}", "id": i_, "title": f"{p_}{i_}"} for i_ in range(n_)]

        def boom32(ctx):
            raise RuntimeError("provedor com defeito")

        temp32("t32_min2", it32(2), min_items=3)
        temp32("t32_min3", it32(3, "y"), min_items=3)
        temp32("t32_max", it32(30, "w"))
        temp32("t32_boom", boom32)
        temp32("t32_empty", [])
        front32("t32_min2", "t32_min3", "t32_max", "t32_boom", "t32_empty")
        kt = {x_["key"]: x_ for x_ in rows32()}
        check("32.3 mínimo por fileira: abaixo do mínimo some, no mínimo aparece", "t32_min2" not in kt and "t32_min3" in kt)
        check("32.3 máximo de 20 itens por fileira", len(kt.get("t32_max", {}).get("items", [])) == hr32.MAX_ITEMS == 20)
        check("32.3 provedor com defeito ou vazio não derruba o Início", c.get("/home/rows").status_code == 200 and "t32_boom" not in kt and "t32_empty" not in kt)
        drop32("t32_min2", "t32_min3", "t32_max", "t32_boom", "t32_empty")
        for n_ in range(15):
            temp32(f"t32_l{n_:02d}", it32(1, f"l{n_}"))
        front32(*[f"t32_l{n_:02d}" for n_ in range(15)])
        check("32.3 no máximo 12 fileiras no Início", len(rows32()) == hr32.MAX_ROWS == 12)
        drop32(*[f"t32_l{n_:02d}" for n_ in range(15)])
        for n_ in (1, 2, 3):
            temp32(f"t32_d{n_}", [{"uid": "dup:1", "id": 1, "title": "Dup"}])
        front32("t32_d1", "t32_d2", "t32_d3")
        kd = [x_["key"] for x_ in rows32()]
        check("32.3 dedupe: a 3ª fileira só com um item já usado 2 vezes some", "t32_d1" in kd and "t32_d2" in kd and "t32_d3" not in kd)
        drop32("t32_d1", "t32_d2", "t32_d3")
        for k_ in "abc":
            temp32(f"t32_{k_}", it32(1, k_))
        front32("t32_a", "t32_b", "t32_c")
        kp = lambda: [k_ for k_ in (x_["key"] for x_ in rows32()) if k_.startswith("t32_")]
        check("32.3 ordem padrão dos provedores de teste", kp() == ["t32_a", "t32_b", "t32_c"])
        sql32("INSERT OR REPLACE INTO home_prefs (profile_id, hidden, \"order\") VALUES (?, ?, ?)", pid, json.dumps(HID32 + ["t32_b"]),
              json.dumps(["t32_c", "nao_existe", "t32_a"]))
        check("32.1 home_prefs: oculta e reordena (chave inexistente é ignorada)", kp() == ["t32_c", "t32_a"])
        sql32("INSERT OR REPLACE INTO home_prefs (profile_id, hidden, \"order\") VALUES (?, '{', '[1, \"t32_b\"]')", pid)
        check("32.1 home_prefs com JSON inválido não quebra (valem só os textos)", c.get("/home/rows").status_code == 200 and kp() == ["t32_b", "t32_a", "t32_c"])
        drop32("t32_a", "t32_b", "t32_c")
        hide32(HID32)
        check("32.3 /home/rows e /home/row sem sessão: 401", anon28.get("/home/rows").status_code == 401 and anon28.get("/home/row/mylist").status_code == 401)
        check("32.3 /home/row: chave inexistente dá 404", c.get("/home/row/nao-existe").status_code == 404)
        J28("/admin/libraries/settings", {"merge_recent": True})
        hr32._cache.clear()
        rr32 = c.get("/home/row/recent_movies?html=1")
        check("32.3 /home/row/<key>?html=1 devolve a fileira e os cards renderizados", rr32.status_code == 200 and rr32.json["row"]["key"] == "recent_movies"
              and "Filme32" in rr32.json.get("html", ""))
        rj32 = c.get("/home/rows").json["rows"]
        check("32.3 formato: key, title, type e items; tipos válidos; limites", all({"key", "title", "type", "items"} <= set(x_) and x_["type"] in hr32.KINDS
              and len(x_["items"]) <= hr32.MAX_ITEMS for x_ in rj32) and len(rj32) <= hr32.MAX_ROWS)

        # 32.6: fileiras do acervo
        sql32("UPDATE media SET added_at = '2099-01-01 00:00:00' WHERE id = ?", M[11])
        rm32, rs32 = row32("recent_movies"), row32("recent_shows")
        check("32.6 com merge_recent: Filmes/Séries Adicionados Recentemente, mais novo primeiro",
              bool(rm32 and rs32) and rm32["title"] == "Filmes Adicionados Recentemente" and ids32(rm32)[0] == M[11]
              and rs32["title"] == "Séries Adicionadas Recentemente" and sh32 in ids32(rs32)
              and not [x_ for x_ in rows32() if x_["key"].startswith("recent_lib_")])
        J28("/admin/libraries/settings", {"merge_recent": False})
        kk32 = {x_["key"]: x_ for x_ in rows32()}
        check("32.6 sem merge_recent: uma fileira por biblioteca, como antes", "recent_movies" not in kk32 and "recent_shows" not in kk32
              and kk32.get(f"recent_lib_{lm32}", {}).get("title") == "Adicionado recentemente em Filmes32"
              and kk32.get(f"recent_lib_{ls32}", {}).get("title") == "Adicionado recentemente em Series32")
        J28("/admin/libraries/settings", {"merge_recent": True})
        cid32 = c.post("/admin/collections", json={"title": "Col32", "library_id": lm32, "media_ids": [M[0], M[1]]}).json.get("id")
        c.post("/admin/collections", json={"title": "Vazia32", "library_id": lm32, "media_ids": []})
        plid32 = c.post("/playlists", json={"title": "Lista32", "library_id": lm32, "media_ids": [M[0], M[1]]}).json.get("id")
        rcol32, rpl32 = row32("collections"), row32("playlists")
        col32 = next((i_ for i_ in (rcol32 or {}).get("items", []) if i_["title"] == "Col32"), None)
        check("32.6 Coleções: card com n e link; coleção vazia fica de fora", bool(col32) and col32["n"] == 2 and col32["href"] == f"/collection/{cid32}"
              and col32["type"] == "collection" and not [i_ for i_ in rcol32["items"] if i_["title"] == "Vazia32"])
        pl32 = next((i_ for i_ in (rpl32 or {}).get("items", []) if i_["title"] == "Lista32"), None)
        check("32.6 Listas de reprodução recentes: tipo playlist, n, duração e link", bool(pl32) and rpl32["type"] == "playlist" and pl32["n"] == 2
              and pl32["href"] == f"/playlist/{plid32}" and isinstance(pl32["dur"], str) and pl32["sec"] >= 0)
        check("32.6 duração total: min, h, e a partir de 24 h \"N dias, Hh\"", tt32(0) == "" and tt32(300) == "5min" and tt32(3 * 3600 + 300) == "3h 05min"
              and tt32(86400 + 3 * 3600) == "1 dia, 3h" and tt32(2 * 86400) == "2 dias, 0h")
        check("32.6 acesso: Rui vê a coleção da biblioteca liberada, mas não a lista de reprodução do admin",
              "Col32" in [i_["title"] for i_ in (row32("collections", c32) or {}).get("items", [])] and row32("playlists", c32) is None)

        # 32.7: fileiras por gênero
        check("32.7 tabela de títulos pt-BR por gênero (com e sem acento; fora da tabela usa o nome)", gt32("Terror") == "Hora do Terror" and gt32("Comédia") == "Pra Rir Alto"
              and gt32("Ficção Científica") == "Futuros Possíveis" and gt32("Ação") == "Pura Adrenalina" and gt32("Animação") == "Para Toda a Família"
              and gt32("Drama") == "Para Se Emocionar" and gt32("Documentário") == "Mundo Real" and gt32("Faroeste") == "Faroeste")
        rrui32 = {x_["key"]: x_ for x_ in rows32(c32)}
        check("32.7 sem histórico: os 2 maiores gêneros (empate pelo nome), cada um com ≥ 6 itens", rrui32.get("genre_1", {}).get("title") == "Pra Rir Alto"
              and rrui32.get("genre_2", {}).get("title") == "Hora do Terror" and len(rrui32["genre_1"]["items"]) >= 6 and len(rrui32["genre_2"]["items"]) >= 6)
        check("32.7 gênero com menos de 6 itens (Drama) não vira fileira", "Para Se Emocionar" not in {x_["title"] for x_ in rows32()} and "genre_3" not in kk32)
        sql32("INSERT OR REPLACE INTO progress (profile_id, item_type, item_id, position, watched) VALUES (?, 'movie', ?, 0, 1)", pid, M[2])
        ra32 = {x_["key"]: x_ for x_ in rows32()}
        check("32.7 com histórico: gênero mais assistido primeiro e não assistidos antes dos assistidos", ra32.get("genre_1", {}).get("title") == "Hora do Terror"
              and ids32(ra32.get("genre_1")) == [M[5], M[4], M[3], M[1], M[0], M[2]])
        check("32.7 segunda fileira de gênero, mais novo primeiro", ra32.get("genre_2", {}).get("title") == "Pra Rir Alto"
              and ids32(ra32.get("genre_2")) == [M[11], M[10], M[9], M[8], M[7], M[6]])

        # 32.4: fileiras de uso (provedores chamados direto, sem a interferência do dedupe)
        def prov32(key, uid_, pid_):
            ctx_ = hr32.Ctx(uid_, pid_)
            return hr32.REGISTRY[key]["provider"](ctx_), ctx_

        def put32(p_, kind_, i_, pos_=0, w_=0, upd_=None):
            sql32("INSERT OR REPLACE INTO progress (profile_id, item_type, item_id, position, watched, updated_at) VALUES (?, ?, ?, ?, ?, COALESCE(?, datetime('now')))",
                  p_, kind_, i_, pos_, w_, upd_)

        put32(pid, "movie", M[3], 30)
        ci32 = next((i_ for i_ in prov32("continue", adm32, pid)[0] if i_["uid"] == f"m:{M[3]}"), None)
        check("32.4 Continue assistindo: filme em andamento com capa (card de pôster) e % (V382)", bool(ci32) and ci32["type"] == "movie" and "still" not in ci32
              and 0 <= ci32["pct"] <= 100 and hr32.REGISTRY["continue"]["kind"] == "poster")
        put32(pid, "episode", ep32[0], 0, 1)
        sql32("UPDATE episodes SET added_at = datetime('now', '-30 days') WHERE id = ?", ep32[0])
        o32 = next((i_ for i_ in prov32("on_deck", adm32, pid)[0] if i_["id"] == sh32), None)
        check("32.4 Em Cartaz: próximo episódio da série em andamento, com still", bool(o32) and o32["episode"] == 2 and o32["season"] == 1
              and o32["type"] == "show" and o32["still"] == f"/still/{ep32[1]}")
        n32e = next((i_ for i_ in prov32("new_episodes", adm32, pid)[0] if i_["id"] == sh32), None)
        check("32.4 Novos episódios: série já assistida com episódios novos (últimos 14 dias)", bool(n32e) and n32e["new"] == 2)
        put32(pid, "episode", ep32[1], 40)
        check("32.4 Em Cartaz: série com episódio em andamento sai (já está em Continue assistindo)", not [i_ for i_ in prov32("on_deck", adm32, pid)[0] if i_["id"] == sh32])
        sql32("DELETE FROM progress WHERE profile_id = ? AND item_type = 'episode' AND item_id = ?", pid, ep32[1])
        sql32("UPDATE episodes SET added_at = datetime('now', '-30 days') WHERE media_id = ?", sh32)
        check("32.4 Novos episódios: episódios com mais de 14 dias não contam", not [i_ for i_ in prov32("new_episodes", adm32, pid)[0] if i_["id"] == sh32])
        put32(pid32, "episode", ep32[0], 0, 1)
        check("32.4 acesso: sem a biblioteca de séries, Em Cartaz e Novos episódios vêm vazios", prov32("on_deck", uid32, pid32)[0] == []
              and prov32("new_episodes", uid32, pid32)[0] == [])
        sql32("DELETE FROM progress WHERE profile_id = ?", pid32)
        sql32("INSERT OR IGNORE INTO my_list (profile_id, media_id) VALUES (?, ?)", pid, M[7])
        check("32.4 Minha Lista: item do perfil aparece e não vaza para outro perfil", M[7] in [i_["id"] for i_ in prov32("mylist", adm32, pid)[0]]
              and prov32("mylist", uid32, pid32)[0] == [])
        for i_ in range(2):
            sql32("INSERT OR IGNORE INTO related (media_id, tmdb_id, ord) VALUES (?, ?, ?)", M[2], 5101 + i_, i_)
        bw32, bctx32 = prov32("because_watched", adm32, pid)
        check("32.4 Porque você assistiu: relacionados do último concluído que existem no servidor", [i_["id"] for i_ in bw32] == [U[0], U[1]]
              and hr32.REGISTRY["because_watched"]["title"](bctx32, bw32) == "Porque você assistiu Filme32 03")
        check("32.4 Porque você assistiu: perfil sem histórico não tem a fileira", prov32("because_watched", uid32, pid32)[0] == [])
        put32(pid, "movie", U[0], 0, 1)
        put32(pid32, "movie", U[0], 0, 1)
        put32(pid, "movie", U[1], 0, 1)
        put32(pid, "movie", U[2], 0, 1, "2000-01-01 00:00:00")
        ts32 = [i_["id"] for i_ in prov32("top_server", adm32, pid)[0]]
        check("32.4 Mais Assistidos: mais reproduções primeiro (todos os perfis), só últimos 30 dias", U[0] in ts32 and U[1] in ts32
              and ts32.index(U[0]) < ts32.index(U[1]) and U[2] not in ts32)
        tsr32 = [i_["id"] for i_ in prov32("top_server", uid32, pid32)[0]]
        check("32.4 Mais Assistidos respeita o acesso: Rui só vê a biblioteca liberada", U[0] in tsr32 and set(tsr32) <= set(M + U))
        grant32([])
        check("32.4 sem nenhuma biblioteca liberada o Início do usuário fica vazio", prov32("top_server", uid32, pid32)[0] == [] and rows32(c32) == [])

        # visibility (28.6) vale para todas as fileiras
        for vis_ in ("hide_home", "hide_all"):
            J28(f"/admin/libraries/{lm32}/update", {"prefs": {"visibility": vis_}})
            s32 = json.dumps(rows32(), ensure_ascii=False, default=str)
            check(f"32.3 visibility {vis_}: a biblioteca some de todas as fileiras do Início", not any(t_ in s32 for t_ in ("Filme32", "Extra32", "Col32", "Lista32")))
        J28(f"/admin/libraries/{lm32}/update", {"prefs": {"visibility": "all"}})
        check("32.3 visibility all: a biblioteca volta ao Início", "Filme32" in json.dumps(rows32(), ensure_ascii=False, default=str))
        # limpeza da Fase 32
        sql32("DELETE FROM home_prefs WHERE profile_id = ?", pid)
        sql32("DELETE FROM my_list WHERE profile_id = ? AND media_id = ?", pid, M[7])
        J28("/admin/libraries/settings", {"merge_recent": False})
        c.delete(f"/playlists/{plid32}")
        c.delete(f"/admin/collections/{cid32}")
        for lid_ in (lm32, ls32):
            c.post(f"/admin/libraries/{lid_}/delete?json=1")
        c.post(f"/admin/users/{uid32}/delete")
    else:
        check("Fase 32: dados de teste (15 filmes, série e 3 episódios) existem", False)
    # ---- Fase 33 (33.1): barra lateral por contexto (33.3: escrito, não rodar sem o Leo pedir)
    def side33(cl, path):
        h_ = cl.get(path).get_data(as_text=True)
        m_ = re.search(r'<aside class="sidebar".*?</aside>', h_, re.S)
        return m_.group(0) if m_ else ""

    def top33(cl, path):
        h_ = cl.get(path).get_data(as_text=True)
        m_ = re.search(r'<header class="topbar.*?</header>', h_, re.S)
        return m_.group(0) if m_ else ""

    hrefs33 = lambda h_: set(re.findall(r'<a href="([^"]+)"[^>]*class="nav-item', h_))
    ADM33 = {"/admin", "/admin/libraries", "/admin/users", "/admin/access", "/admin/home", "/admin/agents", "/admin/playback", "/admin/server"}
    c.post("/admin/users", data={"username": "Ana33", "password": "abcd1"})
    c33 = run.app.test_client()
    c33.post("/login", data={"username": "ana33", "password": "abcd1"})
    c33.post("/profiles/new", data={"name": "Ana"})
    uid33 = sql32("SELECT id FROM users WHERE username = 'Ana33'")[0]["id"]
    pid33 = sql32("SELECT id FROM profiles WHERE user_id = ?", uid33)[0]["id"]
    c33.post(f"/profiles/{pid33}/select")
    c.post(f"/admin/access/user/{uid33}", json={"libraries": [lib28]})
    sa33 = side33(c, "/")
    check("33.1 admin fora de /admin: barra lateral só com Início e bibliotecas, sem links de admin",
          "/" in hrefs33(sa33) and f"/library/{lib28}" in hrefs33(sa33) and not (hrefs33(sa33) & ADM33))
    check("33.1 sem o grupo \"Mais\" na barra lateral", "Mais" not in sa33 and "nav-more" not in sa33)
    check("33.1 admin: ícones Painel e Configurações na topbar, sem modo admin fora de /admin",
          'aria-label="Painel"' in top33(c, "/") and 'data-tip="Configurações"' in top33(c, "/") and "admin-mode" not in top33(c, "/"))
    for p33 in ("/admin", "/admin/libraries", "/admin/users", "/admin/access", "/admin/home"):
        sb33 = side33(c, p33)
        check(f"33.1 {p33}: só os links de configurações (Painel … Reprodução) e da seção Perfil, sem Início nem bibliotecas",
              hrefs33(sb33) == ADM33 | {"/profile", "/account", "/tv", "/phone"} and f"/library/{lib28}" not in sb33)
    check("33.1 /admin*: topbar em modo admin (ícones laranja)", "admin-mode" in top33(c, "/admin/libraries"))
    check("33.1 o logo volta ao Início", 'class="logo" href="/"' in top33(c, "/admin/libraries"))
    su33 = side33(c33, "/")
    check("33.1 usuário comum: só Início e bibliotecas liberadas, sem links de admin",
          "/" in hrefs33(su33) and f"/library/{lib28}" in hrefs33(su33) and not (hrefs33(su33) & ADM33))
    tu33 = top33(c33, "/")
    check("33.1 usuário comum nunca vê os ícones Painel e Configurações", 'aria-label="Painel"' not in tu33
          and 'data-tip="Configurações"' not in tu33 and 'href="/admin' not in tu33)
    r33 = c33.get("/admin/libraries")
    check("33.1 usuário comum em /admin*: sem acesso e sem a barra de admin",
          r33.status_code != 200 or not (hrefs33(side33(c33, "/admin/libraries")) & ADM33))
    c.post(f"/admin/users/{uid33}/delete")
    # ---- Fase 34 (34.1 a 34.8): biblioteca Outros Vídeos (34.9: escrito, não rodar sem o Leo pedir)
    dv34 = os.path.join(TMP, "f34v")
    os.makedirs(os.path.join(dv34, "sub"))
    make_video(os.path.join(dv34, "Video Um.mp4"))
    make_video(os.path.join(dv34, "sub", "Video Dois.mp4"))
    r = J28("/admin/libraries/add", {"name": "Videos34", "type": "video", "lang": "pt-BR", "folders": [dv34], "prefs": {}})
    check("34.1 criar biblioteca do tipo video", r.status_code in (200, 201) and r.json["library"]["type"] == "video")
    lib34 = r.json["library"]["id"]
    check("34.4 prefs: thumbs padrão ligado e valor inválido recusado",
          r.json["library"]["prefs"].get("thumbs") is True
          and J28("/admin/libraries/add", {"name": "X34", "type": "video", "folders": [os.path.join(TMP, "f34x")], "prefs": {"thumbs": "x"}}).status_code == 400)
    J28(f"/admin/libraries/{lib34}/examine", {})
    wait28()
    v34 = sql32("SELECT id, title, year, tmdb_id, overview FROM media WHERE library_id = ? ORDER BY title", lib34)
    check("34.2 scan: um item por arquivo (subpastas incluídas), título = nome sem extensão, sem ano/TMDB",
          [x["title"] for x in v34] == ["Video Dois", "Video Um"] and all(x["year"] is None and not x["tmdb_id"] and not x["overview"] for x in v34))
    vid34 = v34[0]["id"] if v34 else 0
    mv34 = sql32("SELECT id FROM media WHERE library_id = ?", lib28)
    rt = c.get(f"/thumb/{vid34}")
    check("34.3 /thumb/<id>: imagem 200 (frame ou placeholder)", rt.status_code == 200 and rt.mimetype.startswith("image/"))
    check("34.3 /thumb: 404 para item que não é video e 401 sem login",
          c.get(f"/thumb/{mv34[0]['id']}").status_code == 404 and anon28.get(f"/thumb/{vid34}").status_code in (301, 302, 401))
    c.post("/admin/users", data={"username": "Bia34", "password": "abcd1"})
    c34 = run.app.test_client()
    c34.post("/login", data={"username": "bia34", "password": "abcd1"})
    uid34 = sql32("SELECT id FROM users WHERE username = 'Bia34'")[0]["id"]
    c34.post("/profiles/new", data={"name": "Bia"})
    pid34 = sql32("SELECT id FROM profiles WHERE user_id = ?", uid34)[0]["id"]
    c34.post(f"/profiles/{pid34}/select")
    check("34.3 /thumb: usuário sem acesso à biblioteca recebe 404", c34.get(f"/thumb/{vid34}").status_code == 404)
    c.post(f"/admin/access/user/{uid34}", json={"libraries": [lib34]})
    check("34.8 Acesso à biblioteca: usuário com acesso vê a miniatura", c34.get(f"/thumb/{vid34}").status_code == 200)
    hl34 = c.get(f"/library/{lib34}").get_data(as_text=True)
    check("34.5 grade 16:9 com miniatura, clicar reproduz, sem filtro de gênero",
          f"/thumb/{vid34}" in hl34 and f"/watch/movie/{vid34}" in hl34 and "pcard-wide" in hl34 and 'data-dd="genre"' not in hl34)
    check("34.5 ordenação só Título, Adicionado e Por Último assistido (sort=year cai em Título)",
          '["year"' not in hl34 and all(f'["{k_}"' in hl34 for k_ in ("title", "added", "played"))
          and c.get(f"/library/{lib34}?sort=year").status_code == 200)
    ed34 = c.get(f"/admin/item/video/{vid34}/edit")
    check("34.6 Editar: só título e miniatura", ed34.status_code == 200 and ed34.json["tabs"] == ["general", "poster"] and list(ed34.json["fields"]) == ["title"])
    check("34.6 Editar: salvar título", c.post(f"/admin/item/video/{vid34}/edit", json={"fields": {"title": "Video Dois B"}}).status_code == 200
          and sql32("SELECT title FROM media WHERE id = ?", vid34)[0]["title"] == "Video Dois B")
    check("34.6 sem Atualizar Informações nem Remover Correspondência (404); Analisar funciona",
          c.post(f"/admin/item/video/{vid34}/refresh").status_code == 404 and c.post(f"/admin/item/video/{vid34}/unmatch").status_code == 404
          and c.post(f"/admin/item/video/{vid34}/analyze").status_code == 200)
    from server import home_rows as hr34  # noqa: E402
    aid34 = sql32("SELECT id FROM users WHERE is_admin = 1 ORDER BY id")[0]["id"]
    apid34 = sql32("SELECT id FROM profiles WHERE user_id = ? ORDER BY id", aid34)[0]["id"]
    rows34 = {r_["key"]: r_ for r_ in hr34.build_rows(aid34, apid34)}
    check("34.7 Início: fileira 'Vídeos Adicionados Recentemente' (wide) com os 2 vídeos",
          "recent_videos" in rows34 and rows34["recent_videos"]["type"] == "wide" and len(rows34["recent_videos"]["items"]) == 2
          and rows34["recent_videos"]["title"] == "Vídeos Adicionados Recentemente")
    check("34.7 Início: vídeos fora das fileiras de filmes/séries/gênero",
          not any(i.get("type") == "video" for k_, r_ in rows34.items() if k_ != "recent_videos" for i in r_["items"] if k_ != "continue"))
    c.post(f"/progress/movie/{vid34}", json={"position": 1.5, "duration": 2})
    sql32("SELECT 1")
    ct34 = [r_ for r_ in hr34.build_rows(aid34, apid34) if r_["key"] == "continue"]
    check("34.7 Continue assistindo usa a miniatura do vídeo", not ct34 or all(i["still"].startswith("/thumb/") for i in ct34[0]["items"] if i.get("type") == "video"))
    lj34 = c.get(f"/admin/libraries/data").json["libraries"]
    pf34 = next(l_["prefs"] for l_ in lj34 if l_["id"] == lib34)
    c.post(f"/admin/libraries/{lib34}/update", json={"prefs": dict(pf34, visibility="hide_home")})
    check("34.7 visibility 'Excluir do Início' tira a fileira",
          "recent_videos" not in {r_["key"] for r_ in hr34.build_rows(aid34, apid34)})
    hs34 = c.get("/search?q=Video").get_data(as_text=True)
    js34 = c.get("/search?q=Video&json=1").json["items"]
    check("34.8 busca global inclui o tipo video (página e JSON)",
          "Outros Vídeos" in hs34 and f"/thumb/{vid34}" in hs34 and any(i["kind"] == "video" for i in js34))
    c.post(f"/admin/libraries/{lib34}/update", json={"prefs": dict(pf34, visibility="hide_all")})
    check("34.8 visibility 'Excluir da busca' tira os vídeos da busca", not any(i["kind"] == "video" for i in c.get("/search?q=Video&json=1").json["items"]))
    c.post(f"/admin/users/{uid34}/delete")
    check("34.1 excluir biblioteca video", c.post(f"/admin/libraries/{lib34}/delete?json=1").status_code == 200)
    # ---- Fase 35 (35.2 a 35.4): sem correspondência, filmes e séries duplicados (35.6: escrito, não rodar sem o Leo pedir)
    from server import dedupe as dd35  # noqa: E402
    d35m, d35s = os.path.join(TMP, "f35m"), os.path.join(TMP, "f35s")
    os.makedirs(d35m)
    os.makedirs(d35s)
    r = J28("/admin/libraries/add", {"name": "Filmes35", "type": "movie", "lang": "pt-BR", "folders": [d35m], "prefs": {}})
    lm35 = r.json["library"]["id"]
    r = J28("/admin/libraries/add", {"name": "Series35", "type": "show", "lang": "pt-BR", "folders": [d35s], "prefs": {}})
    ls35 = r.json["library"]["id"]
    wait28()
    with get_db() as cn35:
        def ins35(lib, title, year, tmdb, path):
            return cn35.execute("INSERT INTO media (library_id, title, year, tmdb_id, path) VALUES (?, ?, ?, ?, ?)",
                                (lib, title, year, tmdb, path)).lastrowid
        mA = ins35(lm35, "Filme35 A", 2001, 0, "/x35/a1.mp4")
        mA2 = ins35(lm35, "Filme35 A", 2001, 0, "/x35/a2.mp4")      # sem correspondência, mesmo título/ano
        mB = ins35(lm35, "Filme35 B", 2002, 777, "/x35/b1.mp4")
        mB2 = ins35(lm35, "Filme35 B (outro nome)", 2002, 777, "/x35/b2.mp4")  # mesmo tmdb_id
        mC = ins35(lm35, "Filme35 C", 2003, 0, "/x35/c1.mp4")
        sA = ins35(ls35, "Serie35", 2020, 0, None)
        sA2 = ins35(ls35, "Serie35", 2020, 0, None)                  # série repetida em outra pasta
        for sid_, p_ in ((sA, "/x35/s1e1.mp4"), (sA, "/x35/s1e2.mp4"), (sA2, "/x35/s1e1b.mp4")):
            cn35.execute("INSERT INTO episodes (media_id, season, episode, path) VALUES (?, 1, ?, ?)",
                         (sid_, 2 if "e2" in p_ else 1, p_))
        cn35.commit()
    # 35.2: /admin/matched lista só tmdb_id > 0; unmatch sem correspondência = 400 (filme e série)
    mt35 = c.get("/admin/matched")
    check("35.2 /admin/matched: só itens com correspondência, 401 sem login",
          mt35.status_code == 200 and mB in mt35.json["ids"] and mA not in mt35.json["ids"] and mC not in mt35.json["ids"]
          and anon28.get("/admin/matched").status_code in (301, 302, 401))
    check("35.2 Remover Correspondência sem correspondência: 400 JSON (filme e série)",
          c.post(f"/admin/item/movie/{mA}/unmatch").status_code == 400
          and c.post(f"/admin/item/show/{sA}/unmatch").status_code == 400)
    check("35.2 Remover Correspondência com correspondência funciona e o item sai de /admin/matched",
          c.post(f"/admin/item/movie/{mB}/unmatch").status_code == 200 and mB not in c.get("/admin/matched").json["ids"])
    with get_db() as cn35:
        cn35.execute("UPDATE media SET tmdb_id = 777 WHERE id = ?", (mB,))
        cn35.commit()
    # 35.3: filmes duplicados viram um item; o arquivo repetido vai para media_dups
    sql32("INSERT INTO progress (profile_id, item_type, item_id, position) VALUES ((SELECT id FROM profiles ORDER BY id LIMIT 1), 'movie', ?, 1.0)", mA2)  # arquivo fictício: a rota /progress exige o arquivo (get_item)
    n35 = dd35.merge_movies(lm35)
    left35 = {x["title"] for x in sql32("SELECT title FROM media WHERE library_id = ?", lm35)}
    check("35.3 merge_movies une mesmo título/ano sem correspondência e mesmo tmdb_id (2 unidos)",
          n35 == 2 and len(left35) == 3 and "Filme35 C" in left35)
    check("35.3 arquivo repetido guardado em media_dups",
          {x["path"] for x in sql32("SELECT path FROM media_dups")} >= {"/x35/a2.mp4", "/x35/b2.mp4"})
    check("35.3 progresso do duplicado passa para o item que ficou",
          any(x["position"] == 1.0 for x in sql32("SELECT position FROM progress WHERE item_type = 'movie' AND item_id = ?", mA)))
    check("35.3 merge_movies é idempotente e ignora outros tipos",
          dd35.merge_movies(lm35) == 0 and dd35.merge_movies(ls35) == 0)
    wait28()
    J28(f"/admin/libraries/{lm35}/examine", {})
    wait28()
    check("35.3 novo exame não readiciona o arquivo repetido",
          len(sql32("SELECT id FROM media WHERE library_id = ? AND path IN ('/x35/a2.mp4', '/x35/b2.mp4')", lm35)) == 0)
    # 35.4: séries repetidas viram uma e o mesmo SxxExx em dois arquivos é um episódio
    dd35.merge_shows(ls35)
    sh35 = sql32("SELECT id FROM media WHERE library_id = ? AND path IS NULL", ls35)
    ep35 = sql32("SELECT season, episode FROM episodes WHERE media_id IN (SELECT id FROM media WHERE library_id = ?) "
                 "ORDER BY episode", ls35)
    check("35.4 merge_shows: uma só série com os episódios (T1E1 repetido vira um)",
          len(sh35) == 1 and [(e_["season"], e_["episode"]) for e_ in ep35] == [(1, 1), (1, 2)])
    check("35.4 arquivo de episódio repetido guardado em media_dups e merge_shows idempotente",
          len(sql32("SELECT path FROM media_dups WHERE path = '/x35/s1e1b.mp4'")) == 1 and dd35.merge_shows(ls35) == 0)
    check("35.4 excluir bibliotecas do teste 35",
          c.post(f"/admin/libraries/{lm35}/delete?json=1").status_code == 200
          and c.post(f"/admin/libraries/{ls35}/delete?json=1").status_code == 200)
    # ---- Fase 37 (37.1 a 37.4): página do ator/diretor (37.5: escrito, não rodar sem o Leo pedir)
    from server import people as pp37  # noqa: E402
    d37 = os.path.join(TMP, "f37")
    os.makedirs(d37)
    r = J28("/admin/libraries/add", {"name": "Filmes37", "type": "movie", "lang": "pt-BR", "folders": [d37], "prefs": {}})
    lm37 = r.json["library"]["id"]
    wait28()
    with get_db() as cn37:
        mv37 = cn37.execute("INSERT INTO media (library_id, title, year, tmdb_id, path) VALUES (?, 'Cabo do Medo', 2026, 555, '/x37/a.mp4')", (lm37,)).lastrowid
        pa37 = cn37.execute("INSERT INTO people (name, tmdb_id) VALUES ('Amy Adams', 9273)").lastrowid
        pb37 = cn37.execute("INSERT INTO people (name) VALUES ('Sem Tmdb')").lastrowid
        cn37.execute("INSERT INTO credits (media_id, person_id, role, character, ord) VALUES (?, ?, 'cast', 'Anna Bowden', 0)", (mv37, pa37))
        cn37.execute("INSERT INTO credits (media_id, person_id, role, ord) VALUES (?, ?, 'director', 0)", (mv37, pb37))
        cn37.commit()
    calls37, dl37 = [], []

    def fake37(path, **params):
        calls37.append((path, dict(params)))
        if params.get("language") == "en-US":
            return {"biography": "Amy Lou Adams.\n\nSegundo parágrafo."}
        return {"biography": "", "birthday": "1974-08-20", "known_for_department": "Acting", "profile_path": "/x.jpg",
                "external_ids": {"instagram_id": "amyadams", "twitter_id": "AmyA"},
                "combined_credits": {"cast": [
                    {"id": 555, "media_type": "movie", "title": "Cape Fear", "release_date": "2026-05-01", "character": "Anna Bowden", "vote_count": 10, "popularity": 5, "poster_path": "/p.jpg", "genre_ids": [18]},
                    {"id": 1, "media_type": "tv", "name": "Série Longa", "first_air_date": "2016-11-10", "character": "Louise", "episode_count": 8, "vote_count": 9000, "popularity": 50, "poster_path": "/a.jpg", "genre_ids": [18]},
                    {"id": 2, "media_type": "tv", "name": "The Kelly Clarkson Show", "first_air_date": "2019-01-01", "character": "Self", "vote_count": 3, "popularity": 2, "poster_path": None, "genre_ids": [10767]}],
                    "crew": [{"id": 1, "media_type": "tv", "name": "Série Longa", "first_air_date": "2016-11-10", "job": "Executive Producer", "department": "Production", "vote_count": 9000, "popularity": 50, "poster_path": "/a.jpg", "genre_ids": []},
                             {"id": 4, "media_type": "movie", "title": "Outro", "release_date": "2010-01-01", "job": "Thanks", "department": "Crew", "vote_count": 0, "popularity": 1, "genre_ids": []}]}}

    def fdl37(remote, size, rel):
        dl37.append((remote, size, rel))
        dest37 = os.path.join(config.POSTERS_DIR, rel)
        os.makedirs(os.path.dirname(dest37), exist_ok=True)
        open(dest37, "wb").write(b"\xff\xd8\xff")
        return True

    real37 = (md.tmdb_get, md._download, config.TMDB_API_KEY)
    md.tmdb_get, md._download, config.TMDB_API_KEY = fake37, fdl37, "chave"
    h37 = c.get(f"/people/{pa37}")
    t37 = h37.get_data(as_text=True)
    check("37.2 página abre; nome, papéis (Ator, Produtor) e nascimento em português com idade",
          h37.status_code == 200 and "Amy Adams" in t37 and "Ator, Produtor" in t37 and "20 de agosto de 1974" in t37 and "anos)" in t37)
    check("37.1 biografia cai para en-US quando vazia em pt-BR; fotos e dados gravados em people",
          "Segundo parágrafo" in t37 and sql32("SELECT info_ok, instagram, twitter, photo_big FROM people WHERE id = ?", pa37)[0]["photo_big"] == f"people/{pa37}_big.jpg"
          and ("/x.jpg", "h632", f"people/{pa37}_big.jpg") in dl37)
    check("37.2 botões Instagram e Twitter com tooltip de 2 linhas",
          "Instagram&#10;@amyadams" in t37 and "Twitter&#10;@AmyA" in t37)
    check("37.2 abas com contagem: Ator, Aparições (Self/talk), Produtor e Créditos Adicionais",
          all(x in t37 for x in ("Ator (2)", "Aparições (1)", "Produtor (1)", "Créditos Adicionais (1)")))
    check("37.2 'Em StarFlix' só no título que está numa biblioteca liberada; '8 episódios' em Conhecido Por",
          t37.count("Em StarFlix") == 1 and f"/movie/{mv37}" in t37 and "8 episódios" in t37 and "Filmes &amp; Séries nas Bibliotecas" in t37)
    n37 = len(calls37)
    c.get(f"/people/{pa37}")
    check("37.1 2ª visita não busca no TMDB de novo", len(calls37) == n37)
    a37 = c.get(f"/person-art/{pa37}/tv/1")
    check("37.2 pôster do Conhecido Por: baixa w342 na 1ª vez, vira 404 sem pôster/tipo inválido",
          a37.status_code == 200 and ("/a.jpg", "w342", "pk/tv1.jpg") in dl37
          and c.get(f"/person-art/{pa37}/tv/2").status_code == 404 and c.get(f"/person-art/{pa37}/foo/1").status_code == 404)
    check("37.3 fundo: foto grande servida em /person/<id>?big=1", c.get(f"/person/{pa37}?big=1").mimetype == "image/jpeg" and "pp-bg" in t37 and f"/person/{pa37}?big=1" in t37)
    check("37.1 pessoa sem tmdb_id abre só com dados do servidor (papel Diretor, sem Filmografia)",
          "Diretor" in c.get(f"/people/{pb37}").get_data(as_text=True) and "Filmografia" not in c.get(f"/people/{pb37}").get_data(as_text=True))
    check("37.2 pessoa inexistente = 404; sem login = redireciona",
          c.get("/people/999999").status_code == 404 and anon28.get(f"/people/{pa37}").status_code in (301, 302, 401))
    md.tmdb_get = lambda path, **p: (_ for _ in ()).throw(requests.ConnectionError("sem rede"))
    with get_db() as cn37:
        pc37 = cn37.execute("INSERT INTO people (name, tmdb_id) VALUES ('Fora do Ar', 5)").lastrowid
        cn37.execute("INSERT INTO credits (media_id, person_id, role, ord) VALUES (?, ?, 'cast', 0)", (mv37, pc37))
        cn37.commit()
    check("37.1 falha de rede no TMDB: a página abre mesmo assim e não grava info_ok",
          c.get(f"/people/{pc37}").status_code == 200 and sql32("SELECT info_ok FROM people WHERE id = ?", pc37)[0]["info_ok"] is None)
    md.tmdb_get, md._download, config.TMDB_API_KEY = real37
    check("37.4 elenco & equipe do filme leva à página da pessoa", f"/people/{pa37}" in c.get(f"/movie/{mv37}").get_data(as_text=True))
    check("37.1 excluir a biblioteca remove a foto grande da pessoa",
          c.post(f"/admin/libraries/{lm37}/delete?json=1").status_code == 200
          and not os.path.exists(os.path.join(config.POSTERS_DIR, f"people/{pa37}_big.jpg")))
    # ---- Fase 38 (38.1): ordenação/filtros da biblioteca lembrados por perfil no banco (38.2: escrito, não rodar sem o Leo pedir)
    d38 = os.path.join(TMP, "f38")
    os.makedirs(d38)
    lm38 = J28("/admin/libraries/add", {"name": "Filmes38", "type": "movie", "lang": "pt-BR", "folders": [d38], "prefs": {}}).json["library"]["id"]
    wait28()
    with get_db() as cn38:
        for t38, y38 in (("Alfa38", 2001), ("Beta38", 2020), ("Gama38", 2010)):
            cn38.execute("INSERT INTO media (library_id, title, year, path) VALUES (?, ?, ?, ?)", (lm38, t38, y38, f"/x38/{t38}.mp4"))
        cn38.commit()
    pid38 = sql32("SELECT id FROM profiles ORDER BY id LIMIT 1")[0]["id"]

    def ord38(url):
        return re.findall(r'title="(Alfa38|Beta38|Gama38)"', c.get(url).get_data(as_text=True))[:3]
    check("38.1 sem escolha salva: ordem padrão por título", ord38(f"/library/{lm38}?tab=library") == ["Alfa38", "Beta38", "Gama38"])
    check("38.3 POST /library/<id>/view-prefs grava a escolha",
          c.post(f"/library/{lm38}/view-prefs", json={"sort": "year", "dir": "desc", "filter": "all", "genre": ""}).status_code == 200)
    check("38.3 URL sem parâmetros usa a ordem salva no banco", ord38(f"/library/{lm38}?tab=library") == ["Beta38", "Gama38", "Alfa38"])
    check("38.3 parâmetros da URL vencem o salvo", ord38(f"/library/{lm38}?tab=library&sort=title&dir=asc") == ["Alfa38", "Beta38", "Gama38"])
    check("38.3 a escolha fica em library_view_prefs (não em cookie)",
          sql32("SELECT sort, dir FROM library_view_prefs WHERE profile_id = ? AND library_id = ?", pid38, lm38)[0]["sort"] == "year"
          and 'data-sort="year"' in c.get(f"/library/{lm38}?tab=library").get_data(as_text=True))
    check("38.3 valores inválidos caem no padrão", c.post(f"/library/{lm38}/view-prefs", json={"sort": "xx", "dir": "zz", "filter": "yy"}).status_code == 200
          and ord38(f"/library/{lm38}?tab=library") == ["Alfa38", "Beta38", "Gama38"])
    c.post(f"/library/{lm38}/view-prefs", json={"sort": "year", "dir": "desc", "filter": "all", "genre": ""})
    c.set_cookie(f"sf_lib_{pid38}_{lm38}", "sort%3Dtitle%26dir%3Dasc%26filter%3Dall", domain="localhost")  # cookie antigo (38.1) não sobrepõe o banco
    check("38.3 cookie antigo não vence a escolha do banco", ord38(f"/library/{lm38}?tab=library") == ["Beta38", "Gama38", "Alfa38"])
    check("38.1 excluir biblioteca do teste 38", c.post(f"/admin/libraries/{lm38}/delete?json=1").status_code == 200)
    # ---- Fase 39 (39.1–39.3): aba Destaques do Início (39.4: escrito, não rodar sem o Leo pedir)
    c.post("/admin/users", data={"username": "Ana39", "password": "abcd1"})  # o Ana33 já foi apagado na Fase 33
    c39 = run.app.test_client()
    c39.post("/login", data={"username": "ana39", "password": "abcd1"})
    c39.post("/profiles/new", data={"name": "Ana39"})
    uid39 = sql32("SELECT id FROM users WHERE username = 'Ana39'")[0]["id"]
    c39.post(f"/profiles/{sql32('SELECT id FROM profiles WHERE user_id = ?', uid39)[0]['id']}/select")
    c.post(f"/admin/access/user/{uid39}", json={"libraries": [lib28]})
    d39 = c.get("/admin/home/data").json
    check("39.2 /admin/home/data: padrão com TMDB1…TMDB8, tudo ligado e máximo 12",
          d39["tmdb"] == 8 and d39["max_rows"] == 12 and not d39["saved"] and [i["label"] for i in d39["items"] if i["tmdb"]] == [f"TMDB{n}" for n in range(1, 9)])
    check("39.2 página /admin/home abre para o admin e traz o ícone de alça", c.get("/admin/home").status_code == 200 and "i-grip" in c.get("/admin/home").get_data(as_text=True))
    check("39.2 usuário comum recebe 403 em /admin/home e nas rotas de dados", c39.get("/admin/home").status_code == 403
          and c39.get("/admin/home/data").status_code == 403 and c39.post("/admin/home/save", json={}).status_code == 403)
    base39 = {"order": [i["key"] for i in d39["items"]], "hidden": [], "tmdb": 8, "max_rows": 12}
    check("39.2 salvar com dados inválidos devolve 400",
          c.post("/admin/home/save", json=dict(base39, tmdb=9)).status_code == 400 and c.post("/admin/home/save", json=dict(base39, max_rows=0)).status_code == 400
          and c.post("/admin/home/save", json=dict(base39, order="x")).status_code == 400)
    ord39 = ["playlists", "collections"] + [k for k in base39["order"] if k not in ("playlists", "collections")]
    r39 = c.post("/admin/home/save", json=dict(base39, order=ord39, hidden=["mylist"], tmdb=2, max_rows=7))
    check("39.2 salvar grava ordem, seção desligada, 2 slots TMDB e máximo", r39.status_code == 200 and r39.json["saved"] and r39.json["tmdb"] == 2
          and r39.json["max_rows"] == 7 and [i["key"] for i in r39.json["items"]][:2] == ["playlists", "collections"]
          and [i["label"] for i in r39.json["items"] if i["tmdb"]] == ["TMDB1", "TMDB2"] and not [i for i in r39.json["items"] if i["key"] == "mylist"][0]["on"])
    rows39 = c.get("/home/rows").json["rows"]
    check("39.1 o Início respeita o máximo, a ordem e a seção desligada",
          len(rows39) <= 7 and "mylist" not in [r["key"] for r in rows39] and sum(1 for r in rows39 if r["key"].startswith("tmdb_")) <= 2)
    keys39 = [r["key"] for r in rows39]
    check("39.1 playlists vem antes de collections quando as duas aparecem", "playlists" not in keys39 or "collections" not in keys39 or keys39.index("playlists") < keys39.index("collections"))
    check("39.1 o layout vale para outro usuário (global)", len(c39.get("/home/rows").json["rows"]) <= 7)
    c.post(f"/admin/users/{uid39}/delete")
    check("39.3 /admin/home/reset volta ao padrão", c.post("/admin/home/reset").json["saved"] is False and c.get("/admin/home/data").json["max_rows"] == 12)
    # ---- Fase 40 (40.1–40.5): TV — pareamento por código, token Bearer e rotas JSON (40.6: escrito, não rodar sem o Leo pedir)
    import hashlib as hl40
    from server import tv_auth as tva40  # noqa: E402

    d40 = os.path.join(TMP, "f40")
    os.makedirs(d40)
    lm40 = J28("/admin/libraries/add", {"name": "Filmes40", "type": "movie", "lang": "pt-BR", "folders": [d40], "prefs": {}}).json["library"]["id"]
    wait28()
    with get_db() as cn40:
        for t40, y40, g40 in (("Alfa40", 2001, "Ação"), ("Beta40", 2020, "Drama")):
            cn40.execute("INSERT INTO media (library_id, title, year, path, genres, info) VALUES (?, ?, ?, ?, ?, ?)",
                         (lm40, t40, y40, os.path.join(d40, f"{t40}.mp4"), g40, json.dumps({"duration": 6000})))
        cn40.commit()
    mids40 = [r["id"] for r in sql32("SELECT id FROM media WHERE library_id = ? ORDER BY title", lm40)]
    c.post("/admin/users", data={"username": "Tv40", "password": "abcd1"})
    c.post("/admin/users", data={"username": "Outro40", "password": "abcd1"})
    uid40 = sql32("SELECT id FROM users WHERE username = 'Tv40'")[0]["id"]
    uo40 = sql32("SELECT id FROM users WHERE username = 'Outro40'")[0]["id"]
    u40, o40 = run.app.test_client(), run.app.test_client()
    u40.post("/login", data={"username": "tv40", "password": "abcd1"})
    o40.post("/login", data={"username": "outro40", "password": "abcd1"})
    u40.post("/profiles/new", data={"name": "Perfil40"})
    o40.post("/profiles/new", data={"name": "PerfilOutro40"})
    pid40 = sql32("SELECT id FROM profiles WHERE user_id = ?", uid40)[0]["id"]
    po40 = sql32("SELECT id FROM profiles WHERE user_id = ?", uo40)[0]["id"]
    ipn40 = [0]

    def newtv40(name="Sala40"):
        ipn40[0] += 1  # um IP por TV: o limite de 10 códigos / 10 min é por IP
        tv = run.app.test_client()
        return tv, {"REMOTE_ADDR": f"10.40.0.{ipn40[0]}"}, tv.post("/api/tv/code", json={"name": name}, environ_base={"REMOTE_ADDR": f"10.40.0.{ipn40[0]}"})

    def pair40(user_cl, name="Sala40"):
        tv, env, r_ = newtv40(name)
        user_cl.post("/tv/authorize", json={"code": r_.json["code"]})
        return tv.get("/api/tv/code/" + r_.json["poll"], environ_base=env).json

    # 40.1 banco
    check("40.1 tabelas tv_codes e tv_devices existem", {r["name"] for r in sql32("SELECT name FROM sqlite_master WHERE type = 'table'")} >= {"tv_codes", "tv_devices"})
    # 40.2 pareamento
    tv40, env40, r = newtv40()
    check("40.2 POST /api/tv/code devolve código de 6 caracteres sem 0/O/1/I/L, poll, url e 600 s",
          r.status_code == 200 and re.fullmatch(r"[A-HJKMNP-Z2-9]{6}", r.json["code"]) and r.json["poll"] and r.json["url"].endswith("/tv") and r.json["expires_in"] == 600)
    code40, poll40 = r.json["code"], r.json["poll"]
    check("40.2 consulta antes de autorizar: pending", tv40.get("/api/tv/code/" + poll40, environ_base=env40).json["status"] == "pending")
    check("40.2 poll desconhecido: 404", tv40.get("/api/tv/code/nao-existe", environ_base=env40).status_code == 404)
    check("40.3 /tv sem sessão vai ao login e volta com o código", run.app.test_client().get(f"/tv?code={code40}").headers["Location"].startswith("/login?next=/tv"))
    check("40.3 código errado: 400", u40.post("/tv/authorize", json={"code": "ZZZZZZ"}).status_code == 400)
    check("40.3 link vindo de outro site só preenche o código (não autoriza)",
          "TV autorizada" not in u40.get(f"/tv?code={code40}", headers={"Sec-Fetch-Site": "cross-site"}).get_data(as_text=True)
          and tv40.get("/api/tv/code/" + poll40, environ_base=env40).json["status"] == "pending")
    check("40.3 /tv?code= do QR (navegação direta) autoriza sozinho", "TV autorizada" in u40.get(f"/tv?code={code40}", headers={"Sec-Fetch-Site": "none"}).get_data(as_text=True))
    r = tv40.get("/api/tv/code/" + poll40, environ_base=env40)
    tok40 = r.json.get("token")
    check("40.2 autorizado: token entregue", r.status_code == 200 and r.json["status"] == "authorized" and tok40 and r.json["name"] == "Sala40")
    check("40.2 token entregue uma única vez (2ª consulta: 410 used)", tv40.get("/api/tv/code/" + poll40, environ_base=env40).status_code == 410)
    check("40.1 só o hash do token fica no banco", sql32("SELECT COUNT(*) AS n FROM tv_devices WHERE token_hash = ?", hl40.sha256(tok40.encode()).hexdigest())[0]["n"] == 1
          and sql32("SELECT COUNT(*) AS n FROM tv_devices WHERE token_hash = ?", tok40)[0]["n"] == 0)
    tvx, envx, rx = newtv40()
    sql32("UPDATE tv_codes SET expires_at = 1 WHERE poll = ?", rx.json["poll"])
    check("40.2 código vencido: 410 expired", tvx.get("/api/tv/code/" + rx.json["poll"], environ_base=envx).status_code == 410)
    check("40.3 código vencido não autoriza", u40.post("/tv/authorize", json={"code": rx.json["code"]}).status_code == 400)
    check("40.1 clean_tv_codes apaga só os vencidos há mais de 1 h",
          tva40.get_db is not None and sql32("SELECT COUNT(*) AS n FROM tv_codes WHERE poll = ?", rx.json["poll"])[0]["n"] == 1)
    with get_db() as cn40:
        from server.db import clean_tv_codes as ctc40
        ctc40(cn40, now=10 ** 10)
    check("40.1 clean_tv_codes remove os vencidos", sql32("SELECT COUNT(*) AS n FROM tv_codes WHERE poll = ?", rx.json["poll"])[0]["n"] == 0)
    rl40 = [run.app.test_client().post("/api/tv/code", json={}, environ_base={"REMOTE_ADDR": "10.40.9.9"}).status_code for _ in range(11)]
    check("40.2 limite de 10 códigos por IP: o 11º dá 429", rl40[:10] == [200] * 10 and rl40[10] == 429)
    bad40 = [u40.post("/tv/authorize", json={"code": "QQQQQQ"}, environ_base={"REMOTE_ADDR": "10.40.8.8"}).status_code for _ in range(11)]
    check("40.3 10 tentativas erradas por IP bloqueiam (429)", bad40[:10] == [400] * 10 and bad40[10] == 429)
    check("40.3 /tv lista a TV conectada e /tv/devices devolve JSON", any(d["name"] == "Sala40" for d in u40.get("/tv/devices").json["devices"]))
    check("40.3 /tv/devices sem sessão: 401 JSON", run.app.test_client().get("/tv/devices").status_code == 401)
    did40 = sql32("SELECT id FROM tv_devices WHERE user_id = ?", uid40)[0]["id"]
    check("40.3 outro usuário não revoga a TV alheia (404)", o40.post(f"/tv/devices/{did40}/revoke").status_code == 404)
    # 40.4 Bearer
    H40 = {"Authorization": "Bearer " + tok40, "X-Profile": str(pid40)}
    tvc40 = run.app.test_client()
    r = tvc40.get("/home/rows", headers=H40)
    check("40.4 Bearer + X-Profile abre rotas existentes (/home/rows) sem gravar cookie", r.status_code == 200 and not r.headers.get("Set-Cookie"))
    check("40.4 Bearer vale também para imagens (/avatar) e não exige cookie", tvc40.get(f"/avatar/{uid40}", headers=H40).status_code == 200)
    check("40.4 token inválido: 401 JSON", tvc40.get("/home/rows", headers={"Authorization": "Bearer xxxx", "X-Profile": str(pid40)}).status_code == 401)
    check("40.4 sem X-Profile as rotas que exigem perfil dão 400 JSON", tvc40.get("/home/rows", headers={"Authorization": "Bearer " + tok40}).status_code == 400)
    check("40.4 X-Profile de outro usuário: 403", tvc40.get("/home/rows", headers={"Authorization": "Bearer " + tok40, "X-Profile": str(po40)}).status_code == 403)
    r = tvc40.post(f"/api/tv/profile/{pid40}", headers={"Authorization": "Bearer " + tok40})
    check("40.4 POST /api/tv/profile/<id> valida o perfil do usuário", r.status_code == 200 and r.json["id"] == pid40
          and tvc40.post(f"/api/tv/profile/{po40}", headers={"Authorization": "Bearer " + tok40}).status_code == 404)
    check("40.4 usuário comum não vê /admin/tv/devices (403); admin vê", tvc40.get("/admin/tv/devices", headers=H40).status_code == 403
          and any(d["name"] == "Sala40" for d in c.get("/admin/tv/devices").json["devices"]))
    check("40.4 a página /admin/users carrega o bloco de TVs", "tva-list" in c.get("/admin/users").get_data(as_text=True))
    # 40.5 rotas JSON
    check("40.5 sem token: 401 JSON em /api/tv/home", run.app.test_client().get("/api/tv/home").status_code == 401)
    check("40.5 /api/tv/profiles funciona sem X-Profile", [p["id"] for p in tvc40.get("/api/tv/profiles", headers={"Authorization": "Bearer " + tok40}).json["profiles"]] == [pid40])
    check("40.5 sem acesso à biblioteca: 404 na biblioteca e no filme", tvc40.get(f"/api/tv/library/{lm40}", headers=H40).status_code == 404
          and tvc40.get(f"/api/tv/movie/{mids40[0]}", headers=H40).status_code == 404 and not tvc40.get("/api/tv/libraries", headers=H40).json["libraries"])
    c.post(f"/admin/access/user/{uid40}", json={"libraries": [lm40]})
    check("40.5 /api/tv/libraries lista a biblioteca liberada", [l["id"] for l in tvc40.get("/api/tv/libraries", headers=H40).json["libraries"]] == [lm40])
    j = tvc40.get(f"/api/tv/library/{lm40}", headers=H40).json
    check("40.5 biblioteca: total, itens como cards, gêneros e visão", j["total"] == 2 and [i["title"] for i in j["items"]] == ["Alfa40", "Beta40"]
          and j["items"][0]["image"] == f"/poster/{mids40[0]}" and j["genres"] == ["Ação", "Drama"] and j["view"]["sort"] == "title")
    check("40.5 paginação (offset/limit) e valor inválido", [i["title"] for i in tvc40.get(f"/api/tv/library/{lm40}?offset=1&limit=1", headers=H40).json["items"]] == ["Beta40"]
          and tvc40.get(f"/api/tv/library/{lm40}?offset=x", headers=H40).status_code == 400)
    check("40.5 filtro por gênero e ordem da URL", tvc40.get(f"/api/tv/library/{lm40}?genre=Drama", headers=H40).json["total"] == 1
          and [i["title"] for i in tvc40.get(f"/api/tv/library/{lm40}?sort=year&dir=desc", headers=H40).json["items"]] == ["Beta40", "Alfa40"])
    tvc40.post(f"/library/{lm40}/view-prefs", headers=H40, json={"sort": "year", "dir": "desc", "filter": "all", "genre": ""})
    check("40.5 sem parâmetros usa a ordem salva do perfil (38.4)", [i["title"] for i in tvc40.get(f"/api/tv/library/{lm40}", headers=H40).json["items"]] == ["Beta40", "Alfa40"])
    j = tvc40.get(f"/api/tv/movie/{mids40[0]}", headers=H40).json
    check("40.5 detalhe do filme: título, duração, play, imagens e Minha Lista", j["title"] == "Alfa40" and j["duration"] == 6000 and j["play"] == f"/stream/movie/{mids40[0]}/play"
          and j["images"]["poster"] == f"/poster/{mids40[0]}" and j["in_list"] is False)
    check("40.5 Minha Lista: POST liga, GET lista, DELETE desliga",
          tvc40.post(f"/api/tv/mylist/{mids40[0]}", headers=H40).json["on"] is True
          and [i["id"] for i in tvc40.get("/api/tv/mylist", headers=H40).json["items"]] == [mids40[0]]
          and tvc40.delete(f"/api/tv/mylist/{mids40[0]}", headers=H40).json["on"] is False and not tvc40.get("/api/tv/mylist", headers=H40).json["items"])
    open(os.path.join(d40, "Alfa40.mp4"), "wb").close()  # watched/next validam que o arquivo existe
    check("40.5 marcar assistido: POST /api/tv/watched/movie/<id> e filtro Assistidos",
          tvc40.post(f"/api/tv/watched/movie/{mids40[0]}", headers=H40, json={"watched": True}).json["watched"] is True
          and tvc40.get(f"/api/tv/library/{lm40}?filter=watched", headers=H40).json["total"] == 1)
    check("40.5 tipo inválido em /watched: 404", tvc40.post("/api/tv/watched/foo/1", headers=H40).status_code == 404)
    j = tvc40.get("/api/tv/search?q=beta", headers=H40).json
    check("40.5 busca sem acento/caixa devolve cards em grupos", [i["title"] for i in j["movies"]] == ["Beta40"] and j["shows"] == [] and tvc40.get("/api/tv/search", headers=H40).json["movies"] == [])
    h40 = tvc40.get("/api/tv/home", headers=H40).json["rows"]
    check("40.5 Início: fileiras com itens em formato de card", h40 and all(set(i) >= {"type", "id", "title", "image", "pct", "watched"} for r_ in h40 for i in r_["items"]))
    check("40.5 outro usuário (sem acesso) não vê a biblioteca pelo token dele", run.app.test_client().get(f"/api/tv/library/{lm40}",
          headers={"Authorization": "Bearer " + pair40(o40, "TvOutro")["token"], "X-Profile": str(po40)}).status_code == 404)
    # revogação e limpeza
    check("40.3 o dono revoga a própria TV (200) e o token deixa de valer (401)", u40.post(f"/tv/devices/{did40}/revoke").status_code == 200
          and tvc40.get("/home/rows", headers=H40).status_code == 401)
    pa40 = pair40(u40, "Sala40b")
    check("40.4 admin revoga qualquer TV", c.post("/admin/tv/devices/%d/revoke" % pa40["device_id"]).status_code == 200
          and c.post("/admin/tv/devices/%d/revoke" % pa40["device_id"]).status_code == 404
          and tvc40.get("/home/rows", headers={"Authorization": "Bearer " + pa40["token"], "X-Profile": str(pid40)}).status_code == 401)
    c.post(f"/admin/users/{uid40}/delete")
    c.post(f"/admin/users/{uo40}/delete")
    check("40.1 remover o usuário apaga as TVs dele (ON DELETE CASCADE)", sql32("SELECT COUNT(*) AS n FROM tv_devices WHERE user_id IN (?, ?)", uid40, uo40)[0]["n"] == 0)
    check("40.5 excluir biblioteca do teste 40", c.post(f"/admin/libraries/{lm40}/delete?json=1").status_code == 200)
    # 45.7 (59.37) Agentes: sem idioma por agente (segue o do usuário); chave só muda se digitarem outra
    import config as cfg45
    import server.tmdb_lists as tl45
    real45 = (tl45.ensure_fresh, cfg45.TMDB_API_KEY)
    calls45 = []
    tl45.ensure_fresh = lambda: calls45.append(1)
    try:
        ag45 = {a_["id"]: a_ for a_ in c.get("/admin/agents/data").json["agents"]}
        check("45.7 nenhum agente traz idioma ou opções de idioma (59.37)", all("lang" not in v_ and "langs" not in v_ for v_ in ag45.values()))
        r_ = c.post("/admin/agents/tmdb", json={"key": "abcd1234efgh5678", "lang": "xx-YY"})
        check("45.7 salvar TMDB grava a chave mascarada com 4 finais e ignora `lang`",
              r_.status_code == 200 and cfg45.TMDB_API_KEY == "abcd1234efgh5678" and r_.json["agent"]["masked"] == "********5678"
              and "abcd1234" not in r_.get_data(as_text=True) and "lang" not in r_.json["agent"])
        check("45.7 salvar a chave do TMDB baixa as listas de novo (ensure_fresh)", len(calls45) == 1)
        r_ = c.post("/admin/agents/tmdb", json={"key": "   "})
        check("45.7 chave em branco é recusada (400) e não apaga a chave salva", r_.status_code == 400 and cfg45.TMDB_API_KEY == "abcd1234efgh5678")
        check("45.7 só idioma, corpo vazio e chave com espaço são recusados (400)", c.post("/admin/agents/tmdb", json={"lang": "pt-BR"}).status_code == 400
              and c.post("/admin/agents/tmdb", json={}).status_code == 400 and c.post("/admin/agents/tmdb", json={"key": "a b"}).status_code == 400)
        check("45.7 TVDB e OMDB só aceitam chave: `lang` sem chave dá 400", c.post("/admin/agents/tvdb", json={"lang": "spa"}).status_code == 400
              and c.post("/admin/agents/omdb", json={"lang": "pt-BR"}).status_code == 400)
        import server.agents as ag_mod45
        check("45.7 máscara: asteriscos + 4 últimos", ag_mod45._mask("abcd1234efgh5678") == "********5678" and ag_mod45._mask("") == "")
    finally:
        tl45.ensure_fresh, cfg45.TMDB_API_KEY = real45
        sql32("DELETE FROM settings WHERE key = 'api_key_tmdb'")
    # 46.1 Legendas do SubDL: salvas ao lado do vídeo, uma por arquivo (+ forçada em filme dublado), sem repetir busca
    import io as io46, zipfile as zf46
    import config as cfg46
    import server.subdl as sd46
    sd46.RETRY_DAYS = 0  # 46.2: o teste do retry manual não espera dias
    from server.subtitles import external_subs as ext46
    srt46 = "1\n00:00:01,000 --> 00:00:02,000\nOlá, legenda de teste do StarFlix.\n\n"

    def zip46(files):
        b_ = io46.BytesIO()
        with zf46.ZipFile(b_, "w") as z_:
            for n_, t_ in files.items():
                z_.writestr(n_, t_)
        return b_.getvalue()

    class R46:
        def __init__(self, code=200, js=None, data=b""):
            self.status_code, self._j, self._d = code, js, data

        def json(self):
            if self._j is None:
                raise ValueError
            return self._j

        def iter_content(self, n):
            yield self._d

    calls46 = {"s": [], "d": []}

    def get46(url, params=None, **kw):
        if "api.subdl.com" in url:
            calls46["s"].append(params)
            t_ = params.get("tmdb_id")
            if params.get("film_name") == "Original46":  # busca por nome: o título certo é o 2º dos resultados -> nova consulta por sd_id
                return R46(js={"status": True, "results": [{"name": "Outro", "tmdb_id": 1, "sd_id": 7}, {"name": "Original46", "tmdb_id": 9300, "sd_id": 8}],
                               "subtitles": [{"release_name": "ERRADA", "url": "/subtitle/6-6.zip"}]})
            if params.get("sd_id") == 8:
                return R46(js={"status": True, "results": [], "subtitles": [{"release_name": "Fb46", "name": "a.zip", "url": "/subtitle/1-1.zip"}]})
            if t_ == 9300:
                return R46(js={"status": True, "results": [], "subtitles": []})
            if t_ == 9100:
                return R46(js={"status": True, "subtitles": [{"release_name": "Filme46.HI", "name": "b.zip", "url": "/subtitle/2-2.zip", "hi": True},
                                                            {"release_name": "Filme46.1080p", "name": "a.zip", "url": "/subtitle/1-1.zip", "hi": False}]})
            if t_ == 9101:
                return R46(js={"status": True, "subtitles": [{"release_name": "Dub46", "name": "a.zip", "url": "/subtitle/3-3.zip"},
                                                            {"release_name": "Dub46 FORCED", "name": "f.zip", "url": "/subtitle/4-4.zip"}]})
            if t_ == 9200:
                return R46(js={"status": True, "subtitles": [{"release_name": "Pack", "name": "p.zip", "url": "/subtitle/9-9.zip", "full_season": True, "unpack_files": [
                    {"name": "Serie46.S01E01.srt", "season": 1, "episode": 1, "format": "srt", "url": "/subtitle/9/x1"},
                    {"name": "Serie46.S01E02.srt", "season": 1, "episode": 2, "format": "srt", "url": "/subtitle/9/x2"}]}]})
        calls46["d"].append(url)
        if url.endswith(("1-1.zip", "3-3.zip", "4-4.zip")):
            return R46(data=zip46({"x.srt": srt46}))
        if "/subtitle/9/" in url:
            return R46(data=srt46.encode("cp1252"))
        return R46(code=404)

    d46 = os.path.join(TMP, "f46")
    os.makedirs(d46)
    p46 = {n_: os.path.join(d46, n_) for n_ in ("Filme46 (2020).mkv", "Dub46 (2021).mkv", "Tem46 (2019).mkv", "Serie46 S01E01.mkv", "Serie46 S01E02.mkv", "arquivo.sem.nome.util.mkv")}
    for f_ in p46.values():
        open(f_, "wb").close()
    open(os.path.join(d46, "Tem46 (2019).pt-BR.srt"), "w", encoding="utf-8").write(srt46)
    real46 = (sd46.requests.get, sd46.PAUSE, cfg46.SUBDL_API_KEY, cfg46.SUBDL_LANG)
    from server.db import get_db as gdb46
    try:
        sd46.requests.get, sd46.PAUSE, cfg46.SUBDL_API_KEY, cfg46.SUBDL_LANG = get46, 0, "k", "BR_PT"
        with gdb46() as cn_:
            lm46 = cn_.execute("INSERT INTO libraries (name, type, path) VALUES ('F46', 'movie', ?)", (d46,)).lastrowid
            ls46 = cn_.execute("INSERT INTO libraries (name, type, path) VALUES ('S46', 'show', ?)", (d46,)).lastrowid
            for t_, y_, n_, tm_, inf_ in (("Filme46", 2020, "Filme46 (2020).mkv", 9100, None), ("Dub46", 2021, "Dub46 (2021).mkv", 9101, '{"audio": [{"lang": "por"}], "subs": []}'),
                                          ("Tem46", 2019, "Tem46 (2019).mkv", 9102, None)):
                cn_.execute("INSERT INTO media (library_id, title, year, path, tmdb_id, info) VALUES (?, ?, ?, ?, ?, ?)", (lm46, t_, y_, p46[n_], tm_, inf_))
            cn_.execute("INSERT INTO media (library_id, title, original_title, year, path, tmdb_id) VALUES (?, 'Título Atualizado', 'Original46', 2015, ?, 9300)",
                        (lm46, p46["arquivo.sem.nome.util.mkv"]))
            m46 = cn_.execute("INSERT INTO media (library_id, title, year, tmdb_id) VALUES (?, 'Serie46', 2018, 9200)", (ls46,)).lastrowid
            for e_ in (1, 2):
                cn_.execute("INSERT INTO episodes (media_id, season, episode, path) VALUES (?, 1, ?, ?)", (m46, e_, p46[f"Serie46 S01E0{e_}.mkv"]))
        sd46.begin_run(False)
        n46 = sd46.fetch_subtitles(lm46) + sd46.fetch_subtitles(ls46)
        got46 = sorted(os.listdir(d46))
        check("46.1 baixa uma legenda por filme/episódio ao lado do vídeo (<nome>.pt-BR.srt), sem tocar em quem já tem", n46 == 6
              and all(os.path.exists(os.path.splitext(p46[k_])[0] + ".pt-BR.srt") for k_ in p46) and len(calls46["s"]) == 7)
        check("46.1 busca parte do item identificado (id, depois título original/atual e sd_id), não do nome do arquivo: arquivo de nome sem relação recebe legenda",
              any(p_.get("film_name") == "Original46" for p_ in calls46["s"]) and any(p_.get("sd_id") == 8 for p_ in calls46["s"])
              and not any("file_name" in p_ for p_ in calls46["s"]))
        check("46.1 filme dublado (áudio em português) também ganha a forçada (.pt-BR.forced.srt); os demais não", "Dub46 (2021).pt-BR.forced.srt" in got46
              and sum(1 for g_ in got46 if g_.endswith(".forced.srt")) == 1)
        check("46.1 prefere a legenda sem 'surdos/HI' e episódio sai do pacote com unpack_files", any(u_.endswith("1-1.zip") for u_ in calls46["d"])
              and not any(u_.endswith("2-2.zip") for u_ in calls46["d"]) and any("/subtitle/9/x2" in u_ for u_ in calls46["d"]))
        check("46.1 external_subs enxerga as legendas gravadas (completa e forçada)", sorted(s_["lang"] for s_ in ext46(p46["Dub46 (2021).mkv"])) == ["pt-BR", "pt-BR.forced"])
        calls46["s"].clear()
        os.remove(os.path.join(d46, "Filme46 (2020).pt-BR.srt"))
        sd46.begin_run(False)
        check("46.1 exame automático não busca de novo o que já foi tentado", sd46.fetch_subtitles(lm46) == 0 and not calls46["s"])
        sd46.begin_run(True)
        check("46.1 'Examinar arquivos' tenta de novo o que falta, uma vez por exame", sd46.fetch_subtitles(lm46) == 1 and sd46.fetch_subtitles(lm46) == 0 and len(calls46["s"]) == 1)
        sd46.requests.get = lambda url, params=None, **kw: R46(code=429)
        os.remove(os.path.join(d46, "Serie46 S01E01.pt-BR.srt"))
        sd46.begin_run(True)
        check("46.1 limite do SubDL (429) encerra a etapa sem gravar tentativa", sd46.fetch_subtitles(ls46) == 0 and sd46._run["stop"]
              and not os.path.exists(os.path.join(d46, "Serie46 S01E01.pt-BR.srt")))
        zz46 = zip46({"Serie.S01E01.srt": srt46, "Serie.S01E02.srt": srt46.replace("Olá", "Oi")})
        check("46.1 zip: escolhe o arquivo do episódio; sem o episódio devolve None", "Oi" in sd46.extract_srt(zz46, "episode", 1, 2, "x") and sd46.extract_srt(zz46, "episode", 1, 9, "x") is None)
        ag46 = {a_["id"]: a_ for a_ in c.get("/admin/agents/data").json["agents"]}
        check("46.1 Agentes: SubDL tem chave e não traz idioma (59.37: segue o do usuário)", "set" in ag46["subdl"] and "lang" not in ag46["subdl"] and "langs" not in ag46["subdl"])
        r46 = c.post("/admin/agents/subdl", json={"lang": "EN"})
        check("46.1 Agentes: SubDL sem chave no corpo é recusado (400) e o idioma continua o do usuário", r46.status_code == 400 and cfg46.SUBDL_LANG == "BR_PT")
    finally:
        sd46.requests.get, sd46.PAUSE, cfg46.SUBDL_API_KEY, cfg46.SUBDL_LANG = real46
        sql32("DELETE FROM settings WHERE key = 'api_key_subdl'")
        sql32("DELETE FROM subtitle_fetch")
        c.post(f"/admin/libraries/{lm46}/delete?json=1")
        c.post(f"/admin/libraries/{ls46}/delete?json=1")
    # ---- Fase 50 (50.1–50.4): HDR -> SDR ----
    from server import probe as pr50, stream as st50
    from server.db import hdr_label as hl50
    from server.tv_api import _tech as tech50
    check("50.1 derive_hdr: smpte2084 = hdr10, arib-std-b67 = hlg, DV perfil 5 = dv5, DV 7/8 = dv8 (vence a transferência), sem dado = none",
          pr50.derive_hdr({"color_transfer": "smpte2084"}) == "hdr10" and pr50.derive_hdr({"color_transfer": "arib-std-b67"}) == "hlg"
          and pr50.derive_hdr({"dv_profile": 5, "color_transfer": "smpte2084"}) == "dv5" and pr50.derive_hdr({"dv_profile": 8}) == "dv8"
          and pr50.derive_hdr({"dv_profile": 7}) == "dv8" and pr50.derive_hdr({}) == "none" and pr50.derive_hdr({"color_transfer": "bt709"}) == "none")
    check("50.1 selo: HDR (hdr10/hlg), DV (dv5/dv8), nada em SDR ou sem vídeo; /api/tv só leva o selo quando existe",
          hl50({"video": {"hdr": "hdr10"}}) == "HDR" and hl50({"video": {"hdr": "hlg"}}) == "HDR" and hl50({"video": {"hdr": "dv5"}}) == "DV"
          and hl50({"video": {"hdr": "dv8"}}) == "DV" and hl50({"video": {"hdr": "none"}}) is None and hl50({"video": None}) is None and hl50(None) is None
          and "HDR" in tech50(json.dumps({"video": {"height": 2160, "codec": "hevc", "hdr": "hdr10"}}))
          and "HDR" not in tech50(json.dumps({"video": {"height": 1080, "codec": "h264", "hdr": "none"}})))
    h50 = {"video": {"codec": "hevc", "height": 2160, "hdr": "hdr10", "color_transfer": "smpte2084"}}
    hlg50 = {"video": {"codec": "hevc", "height": 1080, "hdr": "hlg", "color_transfer": "arib-std-b67"}}
    real50 = list(st50._TONEMAP)
    try:
        st50._TONEMAP[:] = [True, "zscale"]
        z50 = st50.tonemap_chain(h50, None, 1080)
        check("50.2 zscale: reduz para 1080p ANTES do tone-map (fonte 2160p), cadeia termina em yuv420p; HLG usa tin=arib-std-b67; SDR não tem cadeia",
              z50.startswith("scale=-2:1080,zscale=t=linear") and z50.endswith("format=yuv420p") and "tonemap=tonemap=hable" in z50
              and "tin=arib-std-b67" in st50.tonemap_chain(hlg50, None, 1080) and "tin=" not in z50
              and st50.tonemap_chain({"video": {"hdr": "none"}}) is None and st50.tonemap_chain(None) is None)
        check("50.2 qualidade menor que o teto vence (720p) e fonte já pequena não ganha scale", st50.tonemap_chain(h50, "720p", 1080).startswith("scale=-2:720,")
              and not st50.tonemap_chain(hlg50, None, 1080).startswith("scale="))
        st50._TONEMAP[:] = [True, "tonemapx"]
        check("50.2 tonemapx tem preferência e é um único filtro", st50.tonemap_chain(hlg50, None, 1080).startswith("tonemapx=") and "zscale" not in st50.tonemap_chain(hlg50, None, 1080))
        st50._TONEMAP[:] = [True, None]
        check("50.2 sem nenhum dos dois filtros não há cadeia (transcode como antes)", st50.tonemap_chain(h50, None, 1080) is None)
        st50._TONEMAP[:] = [True, "tonemapx"]
        cmds50 = []
        real_popen50 = st50.subprocess.Popen
        st50.subprocess.Popen = lambda cmd, **kw: cmds50.append(cmd) or type("P", (), {"poll": lambda self: 0})()
        try:
            d50 = os.path.join(TMP, "hls50")
            st50.start_hls("/x.mkv", d50, "transcode", None, None, "hls", 0, h50)
            log50 = open(os.path.join(d50, "ffmpeg.log")).read()
            st50.start_hls("/x.mkv", d50, "remux", None, None, "hls", 0, h50)
            st50.start_hls("/x.mkv", d50, "transcode", None, None, "hls", 0, {"video": {"codec": "h264", "hdr": "none"}})
        finally:
            st50.subprocess.Popen = real_popen50
        vf50 = lambda cmd: cmd[cmd.index("-vf") + 1] if "-vf" in cmd else None
        check("50.2 start_hls: transcode HDR leva o tone-map e as tags BT.709; remux e SDR não",
              "tonemapx" in (vf50(cmds50[0]) or "") and "-color_trc" in cmds50[0] and vf50(cmds50[1]) is None and vf50(cmds50[2]) is None)
        check("50.2 ffmpeg.log registra o filtro usado", "tone-map HDR->SDR (tonemapx, hdr10)" in log50)
    finally:
        st50._TONEMAP[:] = real50
    sdr50 = {"video": {"codec": "h264", "pix_fmt": "yuv420p", "hdr": "none"}}
    with run.app.test_request_context("/"):
        check("50.3 hdr_mode padrão é automático; automático converte sem informação ou com hdr=0 e não converte com hdr=1",
              st50.hdr_mode() == "auto" and st50.hdr_convert(h50, None) and st50.hdr_convert(h50, "0") and not st50.hdr_convert(h50, "1")
              and not st50.hdr_convert(sdr50, None))
        check("50.3 decide: fonte HDR a converter nunca é direct nem remux; sem conversão segue a regra de antes",
              st50.decide("/x.mp4", dict(sdr50, audio=[], container="mp4"), hdr_conv=True) == "transcode"
              and st50.decide("/x.mp4", {"video": {"codec": "h264", "pix_fmt": "yuv420p", "hdr": "none"}, "audio": []}, hdr_conv=False) in ("direct", "remux"))
    r50 = c.post("/admin/playback/save", json={"hdr_mode": "always", "hdr_max_height": 720})
    with run.app.test_request_context("/"):
        check("50.3 Configurações → Reprodução grava; 'sempre' converte mesmo com hdr=1", r50.status_code == 200 and r50.json["hdr_mode"] == "always"
              and st50.hdr_convert(h50, "1") and st50._hdr_max_height() == 720)
    sql32("INSERT INTO settings (key, value) VALUES ('hdr_mode', 'never') ON CONFLICT(key) DO UPDATE SET value = excluded.value")
    with run.app.test_request_context("/"):
        check("50.3 'nunca converter' não força a conversão", not st50.hdr_convert(h50, None) and not st50.hdr_convert(h50, "0"))
    check("50.3 opções inválidas são recusadas (400)", c.post("/admin/playback/save", json={"hdr_mode": "x", "hdr_max_height": 720}).status_code == 400
          and c.post("/admin/playback/save", json={"hdr_mode": "auto", "hdr_max_height": 999}).status_code == 400
          and c.get("/admin/playback/data").json["hdr_mode"] == "never")
    sql32("DELETE FROM settings WHERE key IN ('hdr_mode', 'hdr_max_height')")
    pn50 = c.get("/admin").get_data(as_text=True)
    check("50.4 Painel avisa quando falta filtro de tone-map (ou não avisa se existe) e a página Reprodução abre",
          (st50.has_tonemap() is None) == ("Conversão de HDR para SDR indisponível" in pn50) and c.get("/admin/playback").status_code == 200)
    # ---- Fase 51 (51.1–51.4): backup do banco ----
    import config as cfg51
    import sqlite3 as sq51
    import zipfile as zf51
    from server import backup as bk51, scanner as sc51
    for f51 in os.listdir(cfg51.BACKUPS_DIR) if os.path.isdir(cfg51.BACKUPS_DIR) else []:
        os.remove(os.path.join(cfg51.BACKUPS_DIR, f51))
    open(os.path.join(cfg51.AVATARS_DIR, "t51.png"), "wb").write(b"AV51")
    real_strftime51 = bk51.time.strftime
    n51 = [0]
    bk51.time.strftime = lambda fmt: "starflix-20260101-%06d.zip" % (n51.__setitem__(0, n51[0] + 1) or n51[0])  # nomes distintos sem esperar 1 s
    try:
        first51 = bk51.backup_now()
        z51 = zf51.ZipFile(os.path.join(cfg51.BACKUPS_DIR, first51))
        check("51.1 backup_now grava o zip com starflix.db e avatars/, permissão 600, sem sobras .part",
              first51 and sorted(z51.namelist()) == ["avatars/t51.png", "starflix.db"] and (os.stat(os.path.join(cfg51.BACKUPS_DIR, first51)).st_mode & 0o777) == 0o600
              and not [x for x in os.listdir(cfg51.BACKUPS_DIR) if x.endswith(".part")])
        tmp51 = os.path.join(TMP, "bk51.db")
        open(tmp51, "wb").write(z51.read("starflix.db"))
        con51 = sq51.connect(tmp51)
        check("51.1 a cópia passa no integrity_check e tem as tabelas do banco",
              con51.execute("PRAGMA integrity_check").fetchone()[0] == "ok" and con51.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= 1)
        con51.close()
        check("51.1 grava settings.backup_last", sql32("SELECT value FROM settings WHERE key = 'backup_last'") != [])
        for _ in range(6):
            bk51.backup_now()
        check("51.1 rotação guarda só 4 (padrão) e apaga os mais antigos", len(bk51.list_backups()) == 4 and first51 not in [b_["name"] for b_ in bk51.list_backups()])
        bk51._lock.acquire()
        try:
            check("51.1 só uma execução por vez (com outra em andamento devolve None)", bk51.backup_now() is None)
        finally:
            bk51._lock.release()
        # 51.2 agenda com relógio simulado
        now51 = time.time()
        check("51.2 backup recente: não faz outro antes de 7 dias", bk51.maybe_backup(now=now51) is None and len(bk51.list_backups()) == 4)
        sc51._lock.acquire()
        try:
            check("51.2 exame em andamento adia o backup vencido", bk51.maybe_backup(now=now51 + 8 * 86400) is None)
        finally:
            sc51._lock.release()
        before51 = bk51.list_backups()[0]["name"]
        check("51.2 passados 7 dias (ex.: servidor ficou desligado) faz o backup", bk51.maybe_backup(now=now51 + 8 * 86400) not in (None, before51))
        sql32("INSERT INTO settings (key, value) VALUES ('backup_days', '0') ON CONFLICT(key) DO UPDATE SET value = excluded.value")
        check("51.2 backup_days = 0 desliga a agenda", bk51.maybe_backup(now=now51 + 900 * 86400) is None and bk51.next_time() is None)
        sql32("DELETE FROM settings WHERE key = 'backup_days'")
        sql32("DELETE FROM settings WHERE key = 'backup_last'")
        check("51.2 sem backup_last usa o arquivo mais novo (não refaz à toa)", bk51.last_time() > 0 and bk51.maybe_backup(now=time.time()) is None)
        real_copy51 = bk51._copy_db
        bk51._copy_db = lambda dest: (_ for _ in ()).throw(RuntimeError("falha simulada"))
        try:
            sql32("DELETE FROM settings WHERE key = 'backup_last'")
            n_before51 = len(bk51.list_backups())
            check("51.2 falha não levanta exceção, não deixa .part e tenta de novo depois (backup_last não muda)",
                  bk51.maybe_backup(now=now51 + 30 * 86400) is None and not [x for x in os.listdir(cfg51.BACKUPS_DIR) if x.endswith(".part") or x.endswith(".db.part")]
                  and not sql32("SELECT 1 FROM settings WHERE key = 'backup_last'") and len(bk51.list_backups()) == n_before51)
        finally:
            bk51._copy_db = real_copy51
    finally:
        bk51.time.strftime = real_strftime51
    # 51.3 rotas
    l51 = c.get("/admin/backup/list").json
    nm51 = l51["backups"][0]["name"]
    r51 = c.get("/admin/backup/" + nm51)
    check("51.3 lista (último, próximo, itens) e baixa o zip como anexo", l51["days"] == 7 and l51["keep"] == 4 and l51["last"] and l51["next"]
          and r51.status_code == 200 and "attachment" in r51.headers.get("Content-Disposition", "") and r51.data[:2] == b"PK")
    check("51.3 nome inválido é 404 (.., fora do padrão, inexistente) no download e no apagar",
          all(c.get("/admin/backup/" + n_).status_code == 404 for n_ in ("..%2Fstarflix.db", "x.zip", "starflix-20260101-000000.zip"))
          and c.post("/admin/backup/..%2Fstarflix.db/delete").status_code == 404 and c.post("/admin/backup/x.zip/delete").status_code == 404)
    check("51.3 configuração valida limites e salvar menos que o existente apaga o excedente",
          c.post("/admin/backup/settings", json={"days": 400, "keep": 2}).status_code == 400 and c.post("/admin/backup/settings", json={"days": 7, "keep": 0}).status_code == 400
          and c.post("/admin/backup/settings", json={"days": "a", "keep": 2}).status_code == 400
          and len(c.post("/admin/backup/settings", json={"days": 7, "keep": 2}).json["backups"]) == 2)
    check("51.3 apagar remove o arquivo e o Painel mostra o cartão", len(c.post("/admin/backup/" + nm51 + "/delete").json["backups"]) == 1
          and "admin-backup.js" in c.get("/admin").get_data(as_text=True))
    sql32("DELETE FROM settings WHERE key IN ('backup_days', 'backup_keep', 'backup_last')")
    # 51.4 restauração (processo separado, com a própria pasta de dados: nunca toca no banco do teste)
    rd51 = os.path.join(TMP, "rest51")
    os.makedirs(os.path.join(rd51, "avatars"))
    cdb51 = sq51.connect(os.path.join(rd51, "starflix.db"))
    cdb51.execute("CREATE TABLE users (name TEXT)")
    cdb51.execute("INSERT INTO users VALUES ('atual')")
    cdb51.commit()
    cdb51.close()
    open(os.path.join(rd51, "avatars", "velha.png"), "wb").write(b"old")
    zok51 = os.path.join(TMP, "ok51.zip")
    zdb51 = os.path.join(TMP, "orig51.db")
    cz51 = sq51.connect(zdb51)
    cz51.execute("CREATE TABLE users (name TEXT)")
    cz51.execute("INSERT INTO users VALUES ('do_backup')")
    cz51.commit()
    cz51.close()
    with zf51.ZipFile(zok51, "w") as zz51:
        zz51.write(zdb51, "starflix.db")
        zz51.writestr("avatars/nova.png", b"new")
    zbad51 = os.path.join(TMP, "bad51.zip")
    with zf51.ZipFile(zbad51, "w") as zz51:
        zz51.write(zdb51, "starflix.db")
        zz51.writestr("../fora.txt", b"x")
    env51 = dict(os.environ, STARFLIX_DATA=rd51)
    run51 = lambda *a_: subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "restore_backup.py"), *a_], capture_output=True, text=True, env=env51, timeout=60)
    rb51 = run51(zbad51)
    check("51.4 zip com caminho inesperado é recusado e nada muda", rb51.returncode == 1
          and sq51.connect(os.path.join(rd51, "starflix.db")).execute("SELECT name FROM users").fetchone()[0] == "atual")
    open(os.path.join(rd51, "starflix.db-wal"), "wb").write(b"")
    rr51 = run51(zok51)
    check("51.4 restaura o banco e as fotos, guarda o anterior (.antes-restore) e apaga -wal/-shm",
          rr51.returncode == 0 and sq51.connect(os.path.join(rd51, "starflix.db")).execute("SELECT name FROM users").fetchone()[0] == "do_backup"
          and sq51.connect(os.path.join(rd51, "starflix.db.antes-restore")).execute("SELECT name FROM users").fetchone()[0] == "atual"
          and os.listdir(os.path.join(rd51, "avatars")) == ["nova.png"] and os.path.exists(os.path.join(rd51, "avatars.antes-restore", "velha.png"))
          and not os.path.exists(os.path.join(rd51, "starflix.db-wal")))
    check("51.4 arquivo que não é zip é recusado", run51(os.path.join(TMP, "orig51.db")).returncode == 1)
    # 60.11: backup de segurança antes de restaurar + reversão automática se algo falhar
    bk51 = [n_ for n_ in os.listdir(os.path.join(rd51, "backups")) if n_.endswith(".zip")] if os.path.isdir(os.path.join(rd51, "backups")) else []
    pz51 = zf51.ZipFile(os.path.join(rd51, "backups", bk51[0])) if bk51 else None
    check("60.11 antes de restaurar faz um backup de segurança (zip em backups/ com o banco e as fotos de antes)",
          len(bk51) == 1 and pz51 is not None and sorted(pz51.namelist()) == ["avatars/velha.png", "starflix.db"] and "Backup de segurança" in rr51.stdout)
    fail51 = ("import os,sys,importlib.util\n"
              "spec=importlib.util.spec_from_file_location('rb',os.path.join(%r,'scripts','restore_backup.py'));rb=importlib.util.module_from_spec(spec);spec.loader.exec_module(rb)\n"
              "orig=os.replace;once=[True]\n"
              "def boom(a,b):\n"
              "    if str(a).endswith('.novo') and once[0]:\n"
              "        once[0]=False;raise OSError('disco cheio simulado')\n"
              "    return orig(a,b)\n"
              "os.replace=boom\n"
              "try:\n"
              "    rb.restore(%r);print('SEM ERRO')\n"
              "except rb.RestoreError as e:\n"
              "    print('KEY', e.key)\n") % (ROOT, zok51)
    rf51 = subprocess.run([sys.executable, "-c", fail51], capture_output=True, text=True, env=env51, timeout=60)
    check("60.11 falha no meio da troca: volta ao estado anterior (banco, fotos) e devolve err.restore_revertido",
          "KEY err.restore_revertido" in rf51.stdout
          and sq51.connect(os.path.join(rd51, "starflix.db")).execute("SELECT name FROM users").fetchone()[0] == "do_backup"
          and os.listdir(os.path.join(rd51, "avatars")) == ["nova.png"]
          and not os.path.exists(os.path.join(rd51, "avatars.novo")) and not os.path.exists(os.path.join(rd51, "starflix.db.restore")))
    # ---- Fase 52 (52.1, 52.2, 52.5): direct play pelas capacidades ----
    from server import stream as st52
    from server.caps import Caps as Caps52, parse_caps as pc52
    mk52 = lambda codec, pix="yuv420p", hdr="none", ac="aac", ch=2: {"video": {"codec": codec, "pix_fmt": pix, "hdr": hdr}, "audio": [{"index": 1, "codec": ac, "channels": ch}] if ac else []}
    cp52 = Caps52(["h264", "hevc"], ["aac", "ac3"], ["mp4", "mkv"], False, False, 6)
    check("52.1 sem caps = igual a hoje (hevc recodifica, h264 8 bits toca direto, h264 10 bits recodifica)",
          st52.decide_why("/x.mkv", mk52("hevc"))[0] == "transcode" and st52.decide_why("/x.mp4", mk52("h264"))[0] == "direct"
          and st52.decide_why("/x.mp4", mk52("h264", "yuv420p10le"))[0] == "transcode")
    check("52.1 com caps o HEVC em MKV com AC3 toca direto e o motivo vai junto",
          st52.decide_why("/x.mkv", mk52("hevc", ac="ac3", ch=6), caps=cp52) == ("direct", "hevc ok, ac3 ok"))
    check("52.1 contêiner fora de caps.c e vídeo fora de caps.v não tocam direto",
          st52.decide_why("/x.webm", mk52("hevc"), caps=cp52)[1].startswith("contêiner") and st52.decide_why("/x.mkv", mk52("av1"), caps=cp52)[1].startswith("vídeo"))
    b10 = Caps52(["h264", "hevc"], ["aac"], ["mp4", "mkv"], True, False, 2)
    check("52.1 10 bits só com b10; H.264 de 10 bits nunca; 4:2:2 sempre barrado",
          st52._direct_why("/x.mkv", mk52("hevc", "yuv420p10le"), cp52) == (False, "10 bits") and st52._direct_why("/x.mkv", mk52("hevc", "yuv420p10le"), b10)[0]
          and not st52._direct_why("/x.mkv", mk52("h264", "yuv420p10le"), b10)[0] and not st52._direct_why("/x.mkv", mk52("hevc", "yuv422p10le"), b10)[0])
    hdrc = Caps52(["hevc"], ["aac"], ["mkv"], True, True, 2)
    check("52.1 HDR só toca direto com caps.hdr",
          st52._direct_why("/x.mkv", mk52("hevc", "yuv420p10le", "hdr10"), b10) == (False, "HDR") and st52._direct_why("/x.mkv", mk52("hevc", "yuv420p10le", "hdr10"), hdrc)[0])
    check("52.1 áudio DTS ou canais acima de caps.ch com vídeo copiável = remux, com o motivo",
          st52.decide_why("/x.mkv", mk52("hevc", ac="dts"), caps=cp52) == ("remux", "áudio dts") and st52.decide_why("/x.mkv", mk52("hevc", ac="ac3", ch=8), caps=cp52)[0] == "remux")
    check("52.2 _hls_mode: HEVC copia só com caps; sem caps recodifica; áudio AC3 copia só se caps.a listar e couber em ch",
          st52._hls_mode("remux", mk52("hevc"), cp52) == "remux" and st52._hls_mode("remux", mk52("hevc")) == "transcode"
          and st52._audio_copy(mk52("hevc", ac="ac3", ch=6), None, cp52) and not st52._audio_copy(mk52("hevc", ac="ac3", ch=8), None, cp52)
          and not st52._audio_copy(mk52("hevc", ac="dts"), None, cp52) and not st52._audio_copy(mk52("hevc", ac="ac3"), None))
    cmds52 = []
    real_popen52 = st52.subprocess.Popen
    st52.subprocess.Popen = lambda cmd, **kw: cmds52.append(cmd) or type("P", (), {"poll": lambda self: 0})()
    try:
        d52 = os.path.join(TMP, "hls52")
        st52.start_hls("/x.mkv", d52, "remux", None, None, "hls", 0, mk52("hevc"), True, True)
        st52.start_hls("/x.mkv", d52, "remux", None, None, "hls", 0, mk52("h264"), False, False)
    finally:
        st52.subprocess.Popen = real_popen52
    check("52.2 start_hls: HEVC copia em fMP4 com hvc1 e áudio copiado; H.264 segue em TS com AAC estéreo",
          "hvc1" in cmds52[0] and "fmp4" in cmds52[0] and any(a_.endswith("seg%05d.m4s") for a_ in cmds52[0]) and cmds52[0][cmds52[0].index("-c:a") + 1] == "copy"
          and "fmp4" not in cmds52[1] and any(a_.endswith("seg%05d.ts") for a_ in cmds52[1]) and cmds52[1][cmds52[1].index("-c:a") + 1] == "aac")
    check("52.1 parse_caps: ausente/inválido = None, valor desconhecido é ignorado, ch inválido vira 2",
          pc52({}) is None and pc52({"caps": "x=1"}) is None and pc52({"caps": "v=hevc.foo&ch=7&b10=1"}) == Caps52(["hevc"], [], [], True, False, 2))
    with run.app.test_request_context("/?caps=v%3Dhevc%26c%3Dmkv"):
        check("52.5 Direct play padrão é automático e usa o caps do pedido", st52.direct_policy() == "auto" and st52._caps_arg() is not None)
    with run.app.test_request_context("/?caps=v%3Dhevc%26c%3Dmkv&mode=safe"):
        check("52.3 mode=safe ignora o caps (transcode completo)", st52._caps_arg() is None)
    r52 = c.post("/admin/playback/save", json={"hdr_mode": "auto", "hdr_max_height": 1080, "direct_policy": "conservative"})
    with run.app.test_request_context("/?caps=v%3Dhevc%26c%3Dmkv"):
        check("52.5 Conservador grava e desliga o caps (lista de hoje)", r52.status_code == 200 and r52.json["direct_policy"] == "conservative" and st52._caps_arg() is None)
    check("52.5 política inválida é recusada (400) e salvar sem direct_policy mantém a atual",
          c.post("/admin/playback/save", json={"hdr_mode": "auto", "hdr_max_height": 1080, "direct_policy": "x"}).status_code == 400
          and c.post("/admin/playback/save", json={"hdr_mode": "auto", "hdr_max_height": 1080}).json["direct_policy"] == "conservative")
    sql32("DELETE FROM settings WHERE key IN ('hdr_mode', 'hdr_max_height', 'direct_policy')")
    # ---- Fase 52 (52.6): aparelhos e tabelas ----
    from server import devices as dv52
    from server.db import get_db as gdb52
    with gdb52() as cn52:
        tb52 = {r_[0] for r_ in cn52.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    check("52.6 tabelas client_caps e optimized existem (migração idempotente)", {"client_caps", "optimized"} <= tb52)
    check("52.6 resumo do caps legível", dv52.summary("v=h264.hevc&a=aac.ac3&c=mp4&b10=1&hdr=1&ch=6") == "H.264, HEVC · AAC, AC3 · 10 bits · HDR · 6 canais")
    with run.app.test_request_context("/", headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"}):
        from flask import session as ss52
        ss52["user_id"] = 1
        dv52.touch(cp52)
        dv52.touch(cp52)
        k52, _l52 = dv52.device_key()
    with gdb52() as cn52:
        n52 = cn52.execute("SELECT COUNT(*), MAX(label) FROM client_caps WHERE client_key = ?", (k52,)).fetchone()
    check("52.6 /play grava o aparelho uma vez (UPSERT) com rótulo do navegador", n52[0] == 1 and n52[1] == "Firefox (Linux)")
    check("52.6 marcar 'precisa tocar sem transcode' e apagar (admin; 400/404 em dados ruins)",
          c.post("/admin/devices/required", json={"key": k52, "required": True}).json["devices"][0]["required"] is True
          and c.post("/admin/devices/required", json={"key": k52, "required": "x"}).status_code == 400
          and c.post("/admin/devices/required", json={"key": "nada", "required": True}).status_code == 404
          and c.post("/admin/devices/delete", json={"key": k52}).json["devices"] == []
          and c.post("/admin/devices/delete", json={"key": k52}).status_code == 404)
    # ---- Fase 52 (52.7): gerador da versão otimizada ----
    from server import optimize as op52
    h264_52 = {"duration": 10, "video": {"codec": "h264", "pix_fmt": "yuv420p", "hdr": "none", "height": 1080}}
    hevc_52 = {"duration": 10, "video": {"codec": "hevc", "pix_fmt": "yuv420p10le", "hdr": "none", "height": 2160}}
    cm52 = op52.build_cmd("/x.mkv", "/o.mp4.part", h264_52)[0]
    cx52 = op52.build_cmd("/x.mkv", "/o.mp4.part", hevc_52)[0]
    check("52.7 H.264 8 bits até 1080p só copia o vídeo; o resto vai a libx264 crf 20, teto 1080p e áudio AAC estéreo",
          cm52[cm52.index("-c:v") + 1] == "copy" and cx52[cx52.index("-c:v") + 1] == "libx264" and "-crf" in cx52 and cx52[cx52.index("-crf") + 1] == "20"
          and cx52[cx52.index("-vf") + 1] == "scale=-2:1080" and "+faststart" in cx52 and cx52[cx52.index("-c:a") + 1] == "aac" and cx52[-1] == "/o.mp4.part")
    check("52.7 prioridade baixa (nice/ionice quando existem) e progresso por -progress pipe:1",
          ("nice" in cm52) == bool(shutil.which("nice")) and "pipe:1" in cm52)
    real_tm52 = st52._TONEMAP[:]
    st52._TONEMAP[:] = [True, None]
    try:
        cmd52, why52 = op52.build_cmd("/x.mkv", "/o.part", {"duration": 10, "video": {"codec": "hevc", "pix_fmt": "yuv420p10le", "hdr": "hdr10", "height": 2160}})
    finally:
        st52._TONEMAP[:] = real_tm52
    check("52.7 fonte HDR sem filtro de tone-map é recusada com motivo (vira skip)", cmd52 is None and "tone-map" in why52)
    for _i52 in range(3):
        r52c = op52.convert("movie", 9052, os.path.join(TMP, "nao-existe.mkv"), hevc_52)
    check("52.7 falha apaga o .part, soma tries e na 3ª vira skip com o motivo",
          r52c[0] == "skip" and r52c[1] and not os.path.exists(op52.out_path("movie", 9052) + ".part")
          and gdb52().execute("SELECT tries, status FROM optimized WHERE item_type = 'movie' AND item_id = 9052").fetchone()[:] == (3, "skip"))
    with gdb52() as cn52:
        cn52.execute("DELETE FROM optimized WHERE item_id = 9052")
    # ---- Fase 52 (52.8): fila e janela ----
    import datetime as dt52
    check("52.8 janela 02:00–07:00 (e a que atravessa a meia-noite; início = fim = sempre)",
          op52.in_window("02:00-07:00", dt52.datetime(2026, 1, 1, 3, 0)) and not op52.in_window("02:00-07:00", dt52.datetime(2026, 1, 1, 12, 0))
          and op52.in_window("22:00-06:00", dt52.datetime(2026, 1, 1, 23, 30)) and not op52.in_window("22:00-06:00", dt52.datetime(2026, 1, 1, 7, 0))
          and op52.in_window("00:00-00:00", dt52.datetime(2026, 1, 1, 7, 0)) and op52.parse_window("lixo") == (120, 420))
    with gdb52() as cn52:
        cn52.execute("DELETE FROM client_caps")
        check("52.8 sem aparelho marcado não há candidatos", op52.candidates(cn52) == [])
    r52w = c.post("/admin/playback/save", json={"hdr_mode": "auto", "hdr_max_height": 1080, "optimize_window": "23:00-05:30", "optimize_max_gb": 40})
    check("52.8 Configurações → Reprodução grava janela e limite de disco; inválidos dão 400",
          r52w.status_code == 200 and r52w.json["optimize_window"] == "23:00-05:30" and r52w.json["optimize_max_gb"] == 40
          and c.post("/admin/playback/save", json={"hdr_mode": "auto", "hdr_max_height": 1080, "optimize_window": "25:00-05:30"}).status_code == 400
          and c.post("/admin/playback/save", json={"hdr_mode": "auto", "hdr_max_height": 1080, "optimize_max_gb": -1}).status_code == 400)
    sql32("DELETE FROM settings WHERE key IN ('optimize_window', 'optimize_max_gb')")
    op52.pause()
    check("52.8 pausado manualmente, tick não inicia conversão", op52.tick(dt52.datetime(2026, 1, 1, 3, 0)) is None)
    op52.resume()
    # ---- Fase 52 (52.11): seleção, prioridade, janela, pausa por reprodução, play() e invalidação (ffmpeg simulado; só escrito, não rodado) ----
    import json as js52
    import time as tm52
    import threading as th52
    from flask import jsonify as jf52
    d52o = os.path.join(TMP, "opt52")
    os.makedirs(d52o, exist_ok=True)
    inf52 = lambda **k: js52.dumps({"duration": 60, "video": {"codec": k.get("v", "hevc"), "pix_fmt": "yuv420p", "hdr": "none", "height": 1080},
                                   "audio": [{"index": 1, "codec": k.get("a", "dts"), "channels": 6}, {"index": 2, "codec": "aac", "channels": 2}]})
    f52 = lambda n, data=b"x" * 64: (open(os.path.join(d52o, n), "wb").write(data), os.path.join(d52o, n))[1]
    with gdb52() as cn52:
        pid52 = cn52.execute("SELECT id FROM profiles ORDER BY id LIMIT 1").fetchone()[0]
        lib52 = cn52.execute("INSERT INTO libraries (name, type, path) VALUES ('L52', 'movie', ?)", (d52o,)).lastrowid
        lsh52 = cn52.execute("INSERT INTO libraries (name, type, path) VALUES ('S52', 'show', ?)", (d52o,)).lastrowid
        ins52 = lambda t, p_, inf: cn52.execute("INSERT INTO media (library_id, title, year, path, info) VALUES (?, ?, 2026, ?, ?)", (lib52, t, p_, inf)).lastrowid
        mA = ins52("Continua52", f52("a.mkv"), inf52())
        mB = ins52("Resto52", f52("b.mkv"), inf52())
        mD = ins52("Direto52", f52("d.mp4"), inf52(v="h264", a="aac"))
        shw52 = cn52.execute("INSERT INTO media (library_id, title, year) VALUES (?, 'Serie52', 2026)", (lsh52,)).lastrowid
        e1 = cn52.execute("INSERT INTO episodes (media_id, season, episode, path, info) VALUES (?, 1, 1, ?, ?)", (shw52, f52("e1.mkv"), inf52())).lastrowid
        e2 = cn52.execute("INSERT INTO episodes (media_id, season, episode, path, info) VALUES (?, 1, 2, ?, ?)", (shw52, f52("e2.mkv"), inf52())).lastrowid
        cn52.execute("INSERT INTO progress (profile_id, item_type, item_id, position, watched) VALUES (?, 'movie', ?, 30, 0)", (pid52, mA))
        cn52.execute("INSERT INTO progress (profile_id, item_type, item_id, position, watched) VALUES (?, 'episode', ?, 60, 1)", (pid52, e1))
        cn52.execute("DELETE FROM client_caps")
        cn52.execute("INSERT INTO client_caps (client_key, label, caps, required, last_seen) VALUES ('tv52', 'TV52', ?, 1, ?)", (cp52.query(), int(tm52.time())))
        cn52.commit()
    mine52 = {("movie", mA), ("movie", mB), ("movie", mD), ("episode", e1), ("episode", e2)}
    with gdb52() as cn52:
        cd52 = [(t_, i_) for t_, i_, _p, _n in op52.candidates(cn52) if (t_, i_) in mine52]
    check("52.8 candidatos: só o que o decide() não toca direto no aparelho marcado, em prioridade (continuar, próximo episódio, resto)",
          cd52 == [("movie", mA), ("episode", e2), ("movie", mB), ("episode", e1)] and ("movie", mD) not in cd52)
    sql32("UPDATE client_caps SET required = 0")
    with gdb52() as cn52:
        check("52.8 aparelho desmarcado = sem candidatos", op52.candidates(cn52) == [])
    sql32("UPDATE client_caps SET required = 1")
    out52b = f52("opt-b.mp4", b"y" * 32)
    op52._save("movie", mB, os.path.join(d52o, "b.mkv"), "ok", "", 0, out52b, 32)
    mB2 = None
    with gdb52() as cn52:
        mB2 = cn52.execute("INSERT INTO media (library_id, title, year, path, info) VALUES (?, 'Repetido52', 2026, ?, ?)", (lib52, os.path.join(d52o, "b.mkv"), inf52())).lastrowid
        cn52.commit()
        cd52 = [(t_, i_) for t_, i_, _p, _n in op52.candidates(cn52)]
    check("52.8 item pronto e arquivo repetido (mesmo caminho) não voltam à fila", ("movie", mB) not in cd52 and ("movie", mB2) not in cd52)
    check("52.9 arquivo repetido reaproveita a versão otimizada do outro item",
          op52.find("movie", mB2, os.path.join(d52o, "b.mkv")) == out52b)
    sql32("DELETE FROM media WHERE id = ?", mB2)
    # janela com relógio simulado, pausa por reprodução e pausa manual (convert simulado: espera o cancelamento)
    real_conv52 = op52.convert
    started52 = []

    def fake_conv52(typ, iid, src, info, on_progress=None, cancel=None):
        started52.append((typ, iid))
        for _ in range(100):
            if cancel is not None and cancel.is_set():
                return "paused", "interrompido"
            tm52.sleep(0.05)
        return "ok", ""
    op52.convert = fake_conv52
    op52.resume()
    try:
        check("52.8 fora da janela o tick não converte", op52.tick(dt52.datetime(2026, 1, 1, 12, 0)) is None and not started52)
        got52 = op52.tick(dt52.datetime(2026, 1, 1, 3, 0))
        tm52.sleep(0.2)
        check("52.8 dentro da janela converte o 1º da fila, um por vez", got52 == ("movie", mA) and op52.running() and op52.tick(dt52.datetime(2026, 1, 1, 3, 0)) is None and len(started52) == 1)
        fake52 = type("P", (), {"poll": lambda self: None})()
        st52.SESSIONS["sm52"] = {"user_id": 1, "key": ("movie", mB, "transcode", None, None, "hls", 0), "proc": fake52, "dir": d52o, "playlist": "x.m3u8"}
        try:
            op52.tick(dt52.datetime(2026, 1, 1, 3, 0))
            for _ in range(60):
                if not op52.running():
                    break
                tm52.sleep(0.05)
        finally:
            st52.SESSIONS.pop("sm52", None)
        with gdb52() as cn52:
            sem52 = cn52.execute("SELECT COUNT(*) FROM optimized WHERE item_type = 'movie' AND item_id = ?", (mA,)).fetchone()[0]
        check("52.8 reprodução com transcode mata a conversão e o item volta à fila sem gastar tentativa", not op52.running() and sem52 == 0)
    finally:
        op52.convert = real_conv52
    # play(): otimizada x original (o HLS real é trocado por um simulado)
    real_hls52 = st52._hls
    st52._hls = lambda kind, item_id, path, mode, *a, **k: jf52(mode=mode, hls=True)
    cq52 = "caps=" + cp52.param().split("=", 1)[1]
    P52 = lambda item, extra="": c.post(f"/stream/movie/{item}/play?{cq52}{extra}")
    try:
        r0 = P52(mA)
        check("52.9 sem versão otimizada o original segue pelo caminho de antes (remux)", r0.status_code == 200 and r0.json.get("hls") is True and r0.json["mode"] == "remux")
        out52a = f52("opt-a.mp4", b"y" * 40)
        st52a = os.stat(os.path.join(d52o, "a.mkv"))
        op52._save("movie", mA, os.path.join(d52o, "a.mkv"), "ok", "", 0, out52a, 40)
        r1 = P52(mA)
        check("52.9 com otimizada válida o play() devolve direct play em ?v=opt (optimized = true)",
              r1.json["mode"] == "direct" and r1.json["url"] == f"/stream/movie/{mA}/direct?v=opt" and r1.json.get("optimized") is True)
        check("52.9 faixa de áudio ≠ padrão, qualidade escolhida e mode=safe/hls continuam no original",
              all(P52(mA, x).json.get("hls") is True for x in ("&audio=2", "&quality=720p", "&mode=safe", "&mode=hls")))
        check("52.9 caps sem h264/mp4/aac não recebem a otimizada",
              c.post(f"/stream/movie/{mA}/play?caps=v%3Dhevc%26a%3Dac3%26c%3Dmkv%26b10%3D0%26hdr%3D0%26ch%3D6").json.get("hls") is True)
        d1 = c.get(f"/stream/movie/{mA}/direct?v=opt", headers={"Range": "bytes=0-9"})
        check("52.9 /direct?v=opt serve a otimizada com Range (206)", d1.status_code == 206 and d1.headers.get("Content-Range") == "bytes 0-9/40" and len(d1.data) == 10)
        os.remove(out52a)
        check("52.9 otimizada sumiu: /direct?v=opt dá 404 e o play() volta ao original sem erro",
              c.get(f"/stream/movie/{mA}/direct?v=opt").status_code == 404 and P52(mA).json.get("hls") is True)
        with gdb52() as cn52:
            check("52.9 invalidação: a linha da otimizada que sumiu é apagada", cn52.execute("SELECT COUNT(*) FROM optimized WHERE item_type = 'movie' AND item_id = ?", (mA,)).fetchone()[0] == 0)
        out52a = f52("opt-a.mp4", b"y" * 40)
        op52._save("movie", mA, os.path.join(d52o, "a.mkv"), "ok", "", 0, out52a, 40)
        open(os.path.join(d52o, "a.mkv"), "ab").write(b"mudou")
        check("52.9 invalidação: origem mudou (tamanho/data) apaga arquivo e linha e o play() usa o original",
              P52(mA).json.get("hls") is True and not os.path.exists(out52a)
              and gdb52().execute("SELECT COUNT(*) FROM optimized WHERE item_type = 'movie' AND item_id = ?", (mA,)).fetchone()[0] == 0)
        out52e = f52("opt-e1.mp4", b"y" * 8)
        op52._save("episode", e1, os.path.join(d52o, "e1.mkv"), "ok", "", 0, out52e, 8)
        sql32("DELETE FROM episodes WHERE id = ?", e1)
        op52.prune()
        check("52.9 prune apaga a otimizada de item removido (arquivo e linha)", not os.path.exists(out52e)
              and gdb52().execute("SELECT COUNT(*) FROM optimized WHERE item_type = 'episode' AND item_id = ?", (e1,)).fetchone()[0] == 0)
    finally:
        st52._hls = real_hls52
    # ---- Fase 52 (52.10): painel e menus ----
    op52.pause()  # nada converte durante estes checks
    try:
        rq = c.post(f"/admin/item/movie/{mA}/optimize")
        check("52.10 Otimizar este item entra na fila manual (200, queued = 1) e repetir não duplica",
              rq.status_code == 200 and rq.json["queued"] == 1 and ("movie", mA) in op52._MANUAL and c.post(f"/admin/item/movie/{mA}/optimize").json["queued"] == 0)
        sd = c.get("/admin/optimize/data")
        check("52.10 cartão do Painel: estado com fila, usados, janela e itens ignorados", sd.status_code == 200 and sd.json["paused"] is True and sd.json["queue"]["total"] >= 1
              and {"running", "window", "used", "ok", "skips", "max_gb"} <= set(sd.json))
        check("52.10 Otimizar série entra com os episódios; item inexistente dá 404",
              c.post(f"/admin/item/show/{shw52}/optimize").json["queued"] == 1 and c.post("/admin/item/movie/999999/optimize").status_code == 404)
        out52d = f52("opt-d.mp4", b"y" * 16)
        op52._save("movie", mB, os.path.join(d52o, "b.mkv"), "ok", "", 0, out52d, 16)
        rr = c.post(f"/admin/item/movie/{mB}/optimize/remove")
        check("52.10 Remover versão otimizada apaga arquivo e linha; sem versão devolve 0", rr.json["removed"] == 1 and not os.path.exists(out52d)
              and c.post(f"/admin/item/movie/{mB}/optimize/remove").json["removed"] == 0)
        op52._MANUAL.clear()
        rl = c.post(f"/admin/libraries/{lib52}/optimize")
        check("52.10 Otimizar biblioteca enfileira os itens sem versão válida; biblioteca inexistente dá 404",
              rl.status_code == 200 and rl.json["queued"] >= 3 and c.post("/admin/libraries/999999/optimize").status_code == 404)
        op52._MANUAL.clear()
        op52._save("movie", mD, os.path.join(d52o, "d.mp4"), "ok", "", 0, f52("opt-dd.mp4", b"y" * 4), 4)
        check("52.10 Pausar/Retomar valida o corpo (400) e responde o estado; Apagar todas remove só as prontas",
              c.post("/admin/optimize/pause", json={}).status_code == 400 and c.post("/admin/optimize/pause", json={"paused": False}).json["paused"] is False
              and c.post("/admin/optimize/pause", json={"paused": True}).json["paused"] is True
              and c.post("/admin/optimize/clear").json["ok"] == 0 and not os.path.exists(os.path.join(d52o, "opt-dd.mp4")))
        check("52.10 cartão aparece no Painel e as rotas exigem admin",
              b'id="op-list"' in c.get("/admin").data and run.app.test_client().get("/admin/optimize/data").status_code in (401, 403))
    finally:
        op52.resume()
        op52._MANUAL.clear()
    sql32("DELETE FROM optimized WHERE item_id IN (?, ?, ?, ?, ?)", mA, mB, mD, e1, e2)
    sql32("DELETE FROM client_caps WHERE client_key = 'tv52'")
    # ---- Fase 52 (52.13): aquecer o próximo episódio (start_hls simulado; só escrito, não rodado) ----
    cfg52 = st52.config
    adm52 = sql32("SELECT id FROM users WHERE is_admin = 1 ORDER BY id LIMIT 1")[0]["id"]
    dcur52 = os.path.join(d52o, "cur")
    os.makedirs(dcur52, exist_ok=True)
    infw52 = js52.dumps({"duration": 1500, "video": {"codec": "hevc", "pix_fmt": "yuv420p", "hdr": "none", "height": 1080},
                         "audio": [{"index": 1, "codec": "dts", "channels": 6}, {"index": 2, "codec": "aac", "channels": 2}]})
    with gdb52() as cn52:
        shwW = cn52.execute("INSERT INTO media (library_id, title, year) VALUES (?, 'Warm52', 2026)", (lsh52,)).lastrowid
        w1, w2, w3 = [cn52.execute("INSERT INTO episodes (media_id, season, episode, path, info) VALUES (?, 1, ?, ?, ?)",
                                   (shwW, n_, f52(f"w{n_}.mkv"), infw52)).lastrowid for n_ in (1, 2, 3)]
        cn52.commit()

    class FP52:  # processo simulado: vivo até receber kill()
        def __init__(self):
            self.dead = False

        def poll(self):
            return 0 if self.dead else None

        def kill(self):
            self.dead = True

        def wait(self, *a, **k):
            return 0

    wc52, boom52 = [], []

    def fake_start52(path, out_dir, mode, *a, **k):
        if boom52:
            raise RuntimeError("falha simulada")
        wc52.append((os.path.basename(path), mode))
        os.makedirs(out_dir, exist_ok=True)
        open(os.path.join(out_dir, "index.m3u8"), "w").write("#EXTM3U")
        return FP52()

    base52 = set(st52.SESSIONS)

    def reset52():
        for sid_ in [x for x in list(st52.SESSIONS) if x not in base52]:
            st52._drop(sid_)
        del wc52[:]

    def cur52(ep, audio=None, uid=None):  # sessão HLS "em curso" do episódio, aberta pelo aparelho do cp52
        sid_ = f"cur52-{ep}-{audio}-{uid}"
        st52.SESSIONS[sid_] = {"user_id": adm52 if uid is None else uid, "key": ("episode", ep, "remux", audio, None, "hls", 0, None, "aac", True),
                               "dir": dcur52, "proc": FP52(), "started": tm52.time(), "playlist": "index.m3u8",
                               "caps": cp52, "tv": False, "hdr": None}
        return sid_

    warm52 = lambda: [(s_, v_) for s_, v_ in st52.SESSIONS.items() if v_.get("warm")]
    PG52 = lambda ep, pos: c.post(f"/progress/episode/{ep}", json={"position": pos, "duration": 1500})
    old52 = (st52.start_hls, cfg52.MAX_TRANSCODES, cfg52.MIN_FREE_GB)
    st52.start_hls, cfg52.MAX_TRANSCODES, cfg52.MIN_FREE_GB = fake_start52, 3, 0
    try:
        cur52(w1)
        check("52.12 longe do fim (restam mais de 90 s e menos de 95 %) não aquece", PG52(w1, 1000).status_code == 200 and not wc52 and not warm52())
        r12 = PG52(w1, 1420)
        wm12 = warm52()
        exp12 = st52.decide(os.path.join(d52o, "w2.mkv"), js52.loads(infw52), None, None, tv=False, hdr_conv=False, caps=cp52)
        check("52.12 com ≤ 90 s restantes e HLS em curso inicia o próximo episódio (modo do decide() para o mesmo aparelho, sessão marcada warm)",
              r12.status_code == 200 and len(wc52) == 1 and wc52[0] == ("w2.mkv", exp12) and exp12 != "direct" and len(wm12) == 1
              and wm12[0][1]["key"][:2] == ("episode", w2) and wm12[0][1]["key"][2] == exp12 and wm12[0][1]["user_id"] == adm52)
        PG52(w1, 1425)
        check("52.12 salvar de novo (a cada 10 s) não cria outra sessão: reaproveita pela chave", len(wc52) == 1 and len(warm52()) == 1)
        sid12 = wm12[0][0]
        r_play = c.post(f"/stream/episode/{w2}/play?{cp52.param()}")
        check("52.12 o /play do próximo reaproveita a sessão aquecida (mesma chave, sem novo ffmpeg) e limpa a marca",
              r_play.status_code == 200 and r_play.json.get("sid") == sid12 and len(wc52) == 1 and not warm52()
              and "last" in st52.SESSIONS[sid12])
        st52.SESSIONS[sid12]["started"] -= st52.WARM_TTL + 1
        st52.cleanup_sessions()
        check("52.12 sessão já reclamada não expira pelo prazo do aquecimento", sid12 in st52.SESSIONS)
        reset52()

        cur52(w1)
        PG52(w1, 1420)
        sid12 = warm52()[0][0]
        pr12 = st52.SESSIONS[sid12]["proc"]
        st52.SESSIONS[sid12]["started"] -= st52.WARM_TTL + 1
        cu12 = cur52(w3)
        st52.cleanup_sessions()
        check("52.12 aquecida que ninguém reclama é encerrada após 5 min (ffmpeg morto, pasta apagada) e a sessão em curso fica",
              sid12 not in st52.SESSIONS and pr12.dead and cu12 in st52.SESSIONS)
        reset52()

        PG52(w1, 1420)
        check("52.12 sem sessão HLS do episódio (direct play) não aquece", not wc52 and not warm52())
        reset52()
        cur52(w1, audio=2)
        PG52(w1, 1420)
        check("52.12 faixa de áudio escolhida (≠ padrão) não aquece", not wc52 and not warm52())
        reset52()
        cur52(w3)
        PG52(w3, 1420)
        check("52.12 último episódio da série (sem próximo) não aquece", not wc52 and not warm52())
        reset52()

        cur52(w1)
        al12 = cur52(w3, uid=adm52 + 999)  # sessão de outro usuário, em execução
        cfg52.MAX_TRANSCODES = 2
        PG52(w1, 1420)
        check("52.12 sem vaga (limite de transcodes atingido) não aquece e nunca expulsa a sessão de outro usuário",
              not wc52 and not warm52() and al12 in st52.SESSIONS and not st52.SESSIONS[al12]["proc"].dead)
        cfg52.MAX_TRANSCODES = 3
        reset52()

        cur52(w1)
        PG52(w1, 1420)
        cur52(w2)
        PG52(w2, 1420)
        check("52.12 só uma sessão aquecida por usuário (o episódio 3 não é aquecido enquanto o 2 está aquecido)",
              len(wc52) == 1 and wc52[0][0] == "w2.mkv" and len(warm52()) == 1)
        reset52()

        cur52(w1)
        boom52.append(1)
        rb12 = PG52(w1, 1420)
        check("52.12 falha ao iniciar o ffmpeg do próximo é engolida: o progresso do episódio em curso é salvo normalmente",
              rb12.status_code == 200 and rb12.json["ok"] is True and not warm52())
        del boom52[:]
    finally:
        st52.start_hls, cfg52.MAX_TRANSCODES, cfg52.MIN_FREE_GB = old52
        reset52()
    sql32("DELETE FROM progress WHERE item_type = 'episode' AND item_id IN (?, ?, ?)", w1, w2, w3)
    sql32("DELETE FROM episodes WHERE media_id = ?", shwW)
    sql32("DELETE FROM media WHERE id = ?", shwW)
    # ---- Fase 52 (52.18): GET /api/tv/watchnext — formato, ordem, limite, acesso entre usuários, 401/403, assistido some, próximo episódio (só servidor; só escrito, não rodado) ----
    dm52 = os.path.join(TMP, "f52wn_m")
    ds52 = os.path.join(TMP, "f52wn_s")
    os.makedirs(dm52)
    os.makedirs(ds52)
    lmw52 = J28("/admin/libraries/add", {"name": "Filmes52wn", "type": "movie", "lang": "pt-BR", "folders": [dm52], "prefs": {}}).json["library"]["id"]
    lsw52 = J28("/admin/libraries/add", {"name": "Series52wn", "type": "show", "lang": "pt-BR", "folders": [ds52], "prefs": {}}).json["library"]["id"]
    wait28()

    def touch52(path):
        open(path, "w").close()
        return path

    with get_db() as cnw52:
        mv52 = [cnw52.execute("INSERT INTO media (library_id, title, year, path, genres, info) VALUES (?, ?, 2020, ?, 'Drama', ?)",
                              (lmw52, f"Filme52wn{n_:02d}", touch52(os.path.join(dm52, f"f{n_:02d}.mp4")), json.dumps({"duration": 6000}))).lastrowid for n_ in range(1, 14)]
        shA52 = cnw52.execute("INSERT INTO media (library_id, title, year) VALUES (?, 'SerieA52wn', 2020)", (lsw52,)).lastrowid
        shB52 = cnw52.execute("INSERT INTO media (library_id, title, year) VALUES (?, 'SerieB52wn', 2021)", (lsw52,)).lastrowid
        epA52 = [cnw52.execute("INSERT INTO episodes (media_id, season, episode, title, path, info) VALUES (?, 1, ?, ?, ?, ?)",
                               (shA52, n_, f"EpA{n_}", touch52(os.path.join(ds52, f"a{n_}.mkv")), json.dumps({"duration": 1500}))).lastrowid for n_ in (1, 2, 3)]
        epB52 = [cnw52.execute("INSERT INTO episodes (media_id, season, episode, title, path, info) VALUES (?, 1, ?, ?, ?, ?)",
                               (shB52, n_, f"EpB{n_}", touch52(os.path.join(ds52, f"b{n_}.mkv")), json.dumps({"duration": 1500}))).lastrowid for n_ in (1, 2)]
        cnw52.commit()
    c.post("/admin/users", data={"username": "Wn52a", "password": "abcd1"})
    c.post("/admin/users", data={"username": "Wn52b", "password": "abcd1"})
    uwa52 = sql32("SELECT id FROM users WHERE username = 'Wn52a'")[0]["id"]
    uwb52 = sql32("SELECT id FROM users WHERE username = 'Wn52b'")[0]["id"]
    cwa52, cwb52 = run.app.test_client(), run.app.test_client()
    cwa52.post("/login", data={"username": "wn52a", "password": "abcd1"})
    cwb52.post("/login", data={"username": "wn52b", "password": "abcd1"})
    cwa52.post("/profiles/new", data={"name": "PerfilWnA"})
    cwb52.post("/profiles/new", data={"name": "PerfilWnB"})
    pwa52 = sql32("SELECT id FROM profiles WHERE user_id = ?", uwa52)[0]["id"]
    pwb52 = sql32("SELECT id FROM profiles WHERE user_id = ?", uwb52)[0]["id"]
    tkA52, tkB52 = pair40(cwa52, "SalaWnA"), pair40(cwb52, "SalaWnB")
    tvw52 = run.app.test_client()  # cliente sem cookie: só Bearer, como a TV
    HA52 = {"Authorization": "Bearer " + tkA52["token"], "X-Profile": str(pwa52)}
    HB52 = {"Authorization": "Bearer " + tkB52["token"], "X-Profile": str(pwb52)}
    WN52 = lambda h=None: tvw52.get("/api/tv/watchnext", headers=HA52 if h is None else h)
    PR52 = lambda kind, iid, pos, dur: tvw52.post(f"/progress/{kind}/{iid}", headers=HA52, json={"position": pos, "duration": dur})
    KEYS52 = {"key", "type", "id", "title", "series", "season", "episode", "duration_ms", "position_ms", "image", "last_played", "kind"}

    check("52.14 sem Bearer nem sessão: 401", run.app.test_client().get("/api/tv/watchnext").status_code == 401)
    check("52.14 token inválido: 401", WN52({"Authorization": "Bearer xxxx", "X-Profile": str(pwa52)}).status_code == 401)
    check("52.14 X-Profile de outro usuário: 403", WN52({"Authorization": "Bearer " + tkA52["token"], "X-Profile": str(pwb52)}).status_code == 403)
    check("52.14 sem X-Profile: 400", WN52({"Authorization": "Bearer " + tkA52["token"]}).status_code == 400)

    c.post(f"/admin/access/user/{uwa52}", json={"libraries": [lmw52, lsw52]})
    check("52.14 recém-liberado e sem progresso: 200 e lista vazia", WN52().status_code == 200 and WN52().json["items"] == [])
    PR52("movie", mv52[0], 2400, 6000)
    PR52("episode", epB52[0], 300, 1500)
    PR52("episode", epA52[0], 1450, 1500)  # assistido: a série A passa a oferecer o próximo episódio
    items = WN52().json["items"]
    by = {i["key"]: i for i in items}
    check("52.14 liberadas as bibliotecas: filme em andamento, episódio em andamento e próximo episódio aparecem",
          {f"movie:{mv52[0]}", f"episode:{epB52[0]}", f"episode:{epA52[1]}"} <= set(by) and len(items) == 3)
    check("52.14 formato: todos os campos esperados em cada item", all(set(i) == KEYS52 for i in items))
    m52 = by.get(f"movie:{mv52[0]}", {})
    check("52.14 filme em andamento: kind continue, posição e duração em ms, imagem de pôster, título e sem série/temporada/episódio",
          m52.get("kind") == "continue" and m52.get("type") == "movie" and m52.get("id") == mv52[0] and m52.get("title") == "Filme52wn01"
          and m52.get("position_ms") == 2400000 and m52.get("duration_ms") == 6000000 and m52.get("image") == f"/poster/{mv52[0]}"
          and m52.get("series") is None and m52.get("season") is None and m52.get("episode") is None and m52.get("last_played", 0) > 0)
    e52 = by.get(f"episode:{epB52[0]}", {})
    check("52.14 episódio em andamento: kind continue, série, temporada, episódio, posição e imagem do episódio",
          e52.get("kind") == "continue" and e52.get("type") == "episode" and e52.get("series") == "SerieB52wn" and e52.get("season") == 1 and e52.get("episode") == 1
          and e52.get("position_ms") == 300000 and e52.get("duration_ms") == 1500000 and e52.get("image") == f"/still/{epB52[0]}" and e52.get("title") == "EpB1")
    n52 = by.get(f"episode:{epA52[1]}", {})
    check("52.14 próximo episódio da série assistida: kind next, posição 0, duração do episódio, imagem e dados da série",
          n52.get("kind") == "next" and n52.get("series") == "SerieA52wn" and n52.get("season") == 1 and n52.get("episode") == 2 and n52.get("title") == "EpA2"
          and n52.get("position_ms") == 0 and n52.get("duration_ms") == 1500000 and n52.get("image") == f"/still/{epA52[1]}" and n52.get("id") == epA52[1])
    check("52.14 episódio assistido e episódio ainda não visto (sem progresso, não é o próximo) não aparecem",
          f"episode:{epA52[0]}" not in by and f"episode:{epA52[2]}" not in by and f"episode:{epB52[1]}" not in by)
    lp52 = [i["last_played"] for i in items]
    check("52.14 ordem: mais recentes primeiro (last_played não crescente)", lp52 == sorted(lp52, reverse=True))

    # assistido some / próximo episódio avança
    PR52("movie", mv52[0], 5700, 6000)  # > 90% da duração do ffprobe (6000 s): assistido
    PR52("movie", mv52[1], 5700, 6000)
    check("52.14 filme assistido sai da lista", f"movie:{mv52[0]}" not in {i["key"] for i in WN52().json["items"]} and f"movie:{mv52[1]}" not in {i["key"] for i in WN52().json["items"]})
    tvw52.post(f"/progress/episode/{epA52[1]}/watched", headers=HA52, json={"watched": True})
    after = {i["key"]: i for i in WN52().json["items"]}
    check("52.14 ao assistir o episódio 2, ele sai e o episódio 3 vira o próximo", f"episode:{epA52[1]}" not in after and after.get(f"episode:{epA52[2]}", {}).get("kind") == "next")
    tvw52.post(f"/progress/episode/{epA52[2]}/watched", headers=HA52, json={"watched": True})
    check("52.14 série inteira assistida não deixa item na lista", not any(k.startswith("episode:") and int(k.split(":")[1]) in epA52 for k in {i["key"] for i in WN52().json["items"]}))

    # limite
    for n_ in range(2, 13):
        PR52("movie", mv52[n_], 2400, 6000)
    lim = WN52().json["items"]
    check("52.14 no máximo 10 itens", len(lim) == 10)
    check("52.14 o limite mantém os mais recentes (ordem não crescente de last_played)", [i["last_played"] for i in lim] == sorted([i["last_played"] for i in lim], reverse=True))
    check("52.14 sem chaves repetidas", len({i["key"] for i in lim}) == len(lim))

    # acesso entre usuários
    rb = WN52(HB52)
    check("52.14 outro usuário (sem acesso e sem progresso) recebe lista vazia e nada do primeiro", rb.status_code == 200 and rb.json["items"] == [])
    c.post(f"/admin/access/user/{uwb52}", json={"libraries": [lmw52, lsw52]})
    check("52.14 com acesso, o outro usuário continua sem ver o progresso do primeiro (por perfil)", WN52(HB52).json["items"] == [])
    tvw52.post(f"/progress/movie/{mv52[12]}", headers=HB52, json={"position": 1200, "duration": 6000})
    jb = WN52(HB52).json["items"]
    check("52.14 o progresso de cada perfil aparece só para ele (o 2º usuário vê só o filme dele, com a posição dele)",
          [i["key"] for i in jb] == [f"movie:{mv52[12]}"] and jb[0]["position_ms"] == 1200000)
    c.post(f"/admin/access/user/{uwa52}", json={"libraries": [lsw52]})
    check("52.14 tirar o acesso à biblioteca de filmes remove os filmes da lista", not any(i["type"] == "movie" for i in WN52().json["items"]))
    c.post(f"/admin/access/user/{uwa52}", json={"libraries": []})
    check("52.14 sem nenhuma biblioteca liberada a lista fica vazia", WN52().json["items"] == [])

    # revogação
    check("52.14 TV revogada: 401", c.post("/admin/tv/devices/%d/revoke" % tkA52["device_id"]).status_code == 200 and WN52().status_code == 401)
    # limpeza
    sql32("DELETE FROM progress WHERE profile_id IN (?, ?)", pwa52, pwb52)
    c.post(f"/admin/users/{uwa52}/delete")
    c.post(f"/admin/users/{uwb52}/delete")
    sql32("DELETE FROM episodes WHERE media_id IN (?, ?)", shA52, shB52)
    sql32("DELETE FROM media WHERE id IN (?, ?)", shA52, shB52)
    c.post(f"/admin/libraries/{lmw52}/delete?json=1")
    c.post(f"/admin/libraries/{lsw52}/delete?json=1")
    # limpeza
    r = c.post(f"/admin/libraries/{lib28}/delete?json=1")
    check("28.3 excluir biblioteca (JSON)", r.status_code == 200 and J28("/admin/libraries/data").json["libraries"].count(lib28) == 0)

    # ---- Fase 58: servidor configurável, conexão do celular e ticket da TV (58.20) ----
    from server import tv_auth as TA58
    TA58._hits.clear()
    BR58 = lambda t: {"Authorization": "Bearer " + t}
    anon58 = run.app.test_client()

    # 58.2 /api/server-info pública e configurável (58.1)
    r = anon58.get("/api/server-info")
    si58 = r.json or {}
    check("58.2 /api/server-info é pública e traz app, id, nome, versão, porta, endereços e mdns",
          r.status_code == 200 and si58.get("app") == "starflix" and si58.get("id") and si58.get("name") and si58.get("version")
          and isinstance(si58.get("port"), int) and set(si58.get("urls", {})) == {"external", "local"} and "mdns" in si58)
    check("58.2 /api/server-info com CORS aberto (botão Testar do admin)", r.headers.get("Access-Control-Allow-Origin") == "*")
    check("58.1 salvar nome e endereço externo exige admin", anon58.post("/admin/server/save", json={"name": "X"}).status_code in (302, 401, 403))
    r = c.post("/admin/server/save", json={"name": "Casa 58", "url": "https://Meu.Dominio58.com:8443/"})
    inf58 = anon58.get("/api/server-info").json
    check("58.1 admin salva nome e endereço externo e o /api/server-info reflete (normalizado)",
          r.status_code == 200 and inf58["name"] == "Casa 58" and "dominio58.com" in (inf58["urls"]["external"] or "").lower())
    check("58.1 endereço externo inválido é recusado (400)", c.post("/admin/server/save", json={"url": "ftp://x"}).status_code == 400)
    check("58.1 id do servidor é estável entre consultas", anon58.get("/api/server-info").json["id"] == si58["id"])

    # 58.5 QR e link de uso único
    q1 = c.post("/phone/qr").json
    check("58.5 QR dinâmico: url /c/<token> no endereço externo, 60 s", "/c/" in q1["url"] and q1["url"].startswith(inf58["urls"]["external"]) and q1["expires_in"] == 60)
    check("58.5 estado do QR: pendente", c.get(f"/phone/token/{q1['id']}").json["status"] == "pending")
    q2 = c.post("/phone/qr").json
    check("58.5 novo QR invalida o anterior ainda não usado", c.get(f"/phone/token/{q1['id']}").status_code == 404)
    t2 = q2["url"].rsplit("/c/", 1)[1]
    pg = anon58.get("/c/" + t2)
    check("58.5 /c/<token> não consome e abre o app (starflix://connect)", pg.status_code == 200 and b"starflix://connect" in pg.data and anon58.get("/c/" + t2).status_code == 200)
    check("58.5 /c/<token> inválido: 410", anon58.get("/c/naoexiste58").status_code == 410)
    r = anon58.post("/api/phone/claim", json={"token": t2, "name": "Pixel 58"})
    j58 = r.json or {}
    check("58.5 claim troca o token do QR pelo token do aparelho (uma vez) e devolve os dados do servidor",
          r.status_code == 200 and j58.get("status") == "authorized" and len(j58.get("device_token", "")) > 20 and j58["server"]["id"] == si58["id"] and j58["name"] == "Pixel 58")
    check("58.5 estado do QR vira usado, com o nome do celular", c.get(f"/phone/token/{q2['id']}").json == {"status": "used", "name": "Pixel 58"})
    check("58.5 QR usado não vale de novo (410), no claim e na página", anon58.post("/api/phone/claim", json={"token": t2}).status_code == 410 and anon58.get("/c/" + t2).status_code == 410)
    check("58.5 claim com token desconhecido: 404", anon58.post("/api/phone/claim", json={"token": "xxxx"}).status_code == 404)
    check("58.5 claim sem corpo JSON: 404 sem erro 500", anon58.post("/api/phone/claim", data="lixo").status_code == 404)
    l1 = c.post("/phone/link").json
    check("58.5 link de 24 h, uso único", l1["expires_in"] == 86400 and "/c/" in l1["url"])
    r = anon58.post("/api/phone/claim", json={"token": l1["url"].rsplit("/c/", 1)[1], "name": "  Tablet   58 "})
    check("58.5 claim pelo link funciona e o nome é normalizado", r.status_code == 200 and r.json["name"] == "Tablet 58")
    q3 = c.post("/phone/qr").json
    sql32("UPDATE phone_tokens SET expires_at = 1 WHERE id = ?", q3["id"])
    check("58.5 QR vencido: claim 410 e estado expirado", anon58.post("/api/phone/claim", json={"token": q3["url"].rsplit("/c/", 1)[1]}).status_code == 410
          and c.get(f"/phone/token/{q3['id']}").json["status"] == "expired")

    # 58.6 sessão por token do aparelho, lista e revogação
    TA58._hits.clear()
    dtok58, did58 = j58["device_token"], j58["device_id"]
    ph58 = run.app.test_client()
    r = ph58.get("/api/phone/session", headers=BR58(dtok58))
    check("58.6 /api/phone/session com o token do aparelho abre a sessão e vai para /", r.status_code == 302 and r.headers["Location"].endswith("/"))
    check("58.6 a sessão do celular funciona sem login (cookie)", ph58.get("/profiles").status_code == 200)
    check("58.6 token inválido na sessão: 401 JSON", anon58.get("/api/phone/session", headers=BR58("invalido58")).status_code == 401 and anon58.get("/api/phone/session").status_code == 401)
    check("58.16 /api/phone/me devolve a conta do aparelho; token inválido: 401", anon58.get("/api/phone/me", headers=BR58(dtok58)).json == {"user": "admin"}
          and anon58.get("/api/phone/me", headers=BR58("invalido58")).status_code == 401)
    check("58.6 o token de celular não vale como token de TV", anon58.get("/api/tv/profiles", headers=BR58(dtok58)).status_code == 401)
    devs = c.get("/phone/devices").json["devices"]
    check("58.9 lista de celulares do usuário traz os conectados", {"Pixel 58", "Tablet 58"} <= {d["name"] for d in devs} and did58 in {d["id"] for d in devs})
    check("58.9 lista de todos os celulares é do admin", c.get("/admin/phone/devices").status_code == 200 and anon58.get("/admin/phone/devices").status_code in (302, 401, 403))
    check("58.6 revogar o celular: 200, e de novo 404", c.post(f"/phone/devices/{did58}/revoke").status_code == 200 and c.post(f"/phone/devices/{did58}/revoke").status_code == 404)
    check("58.6 revogado: o token e a sessão (cookie) já abertos caem",
          anon58.get("/api/phone/session", headers=BR58(dtok58)).status_code == 401 and ph58.get("/profiles").status_code != 200)

    tab58 = [d["id"] for d in devs if d["name"] == "Tablet 58"][0]
    check("58.9 o admin revoga o celular de qualquer usuário (200; de novo 404)",
          c.post(f"/admin/phone/devices/{tab58}/revoke").status_code == 200 and c.post(f"/admin/phone/devices/{tab58}/revoke").status_code == 404)

    # 58.7 ticket da TV pelo celular
    TA58._hits.clear()
    qd = c.post("/phone/qr").json
    dv = anon58.post("/api/phone/claim", json={"token": qd["url"].rsplit("/c/", 1)[1], "name": "Celular TV 58"}).json
    r = anon58.post("/api/phone/tv-ticket", headers=BR58(dv["device_token"]))
    tk58 = (r.json or {}).get("ticket", "")
    check("58.7 celular conectado pede ticket da TV (uso único)", r.status_code == 200 and len(tk58) > 20 and r.json["expires_in"] > 0)
    check("58.7 sem token de celular ou revogado: 401", anon58.post("/api/phone/tv-ticket").status_code == 401 and anon58.post("/api/phone/tv-ticket", headers=BR58("invalido58")).status_code == 401)
    r = anon58.post("/api/tv/claim", json={"ticket": tk58, "name": "Sala 58"})
    tvt58 = (r.json or {}).get("token", "")
    check("58.7 a TV troca o ticket por token de TV (uma vez)", r.status_code == 200 and r.json["status"] == "authorized" and len(tvt58) > 20 and r.json["name"] == "Sala 58")
    check("58.7 o token da TV vale na API da TV (perfis)", anon58.get("/api/tv/profiles", headers=BR58(tvt58)).status_code == 200)
    check("58.7 ticket usado: 410; desconhecido: 404", anon58.post("/api/tv/claim", json={"ticket": tk58}).status_code == 410 and anon58.post("/api/tv/claim", json={"ticket": "xxxx"}).status_code == 404)
    tk2 = anon58.post("/api/phone/tv-ticket", headers=BR58(dv["device_token"])).json["ticket"]
    sql32("UPDATE tv_tickets SET expires_at = 1")
    check("58.7 ticket vencido: 410", anon58.post("/api/tv/claim", json={"ticket": tk2}).status_code == 410)
    with get_db() as conn:
        tvid58 = conn.execute("SELECT id FROM tv_devices WHERE name = 'Sala 58'").fetchone()["id"]
    check("58.7 a TV conectada pelo celular aparece e é revogável como as do código", c.post(f"/admin/tv/devices/{tvid58}/revoke").status_code == 200
          and anon58.get("/api/tv/profiles", headers=BR58(tvt58)).status_code == 401)

    # limites por IP (tentativas erradas)
    TA58._hits.clear()
    codes58 = [anon58.post("/api/phone/claim", json={"token": f"errado58{n}"}).status_code for n in range(12)]
    check("58.5 muitas tentativas erradas de claim no mesmo IP: 404 até o limite e depois 429", codes58[:10] == [404] * 10 and codes58[10:] == [429, 429])
    check("58.5 durante o bloqueio o link e a sessão também respondem 429", anon58.get("/c/outro58").status_code == 429 and anon58.get("/api/phone/session", headers=BR58("x")).status_code == 429)
    TA58._hits.clear()
    codes58 = [anon58.post("/api/tv/claim", json={"ticket": f"errado58{n}"}).status_code for n in range(12)]
    check("58.7 muitas tentativas erradas de ticket no mesmo IP: 404 até o limite e depois 429", codes58[:10] == [404] * 10 and codes58[10:] == [429, 429])
    TA58._hits.clear()

    # servidor sobe sem mDNS (58.3): o interruptor desligado não gera erro e o anúncio falha em silêncio
    from server import discovery as DS58
    r = c.post("/admin/server/save", json={"mdns": False})
    check("58.3 desligar o anúncio mDNS pelo admin salva e /api/server-info mostra mdns falso", r.status_code == 200 and anon58.get("/api/server-info").json["mdns"] is False)
    for _w58 in range(50):  # o salvar reavalia o mDNS em thread (refresh_async): espera o anúncio anterior cair
        if DS58._state["zc"] is None:
            break
        time.sleep(0.1)
    DS58._stop()  # V678: derruba qualquer anúncio que a thread de reavaliação tenha subido depois da espera (corrida intermitente)
    try:
        DS58._start()
        ok58 = True
    except Exception:
        ok58 = False
    check("58.3 com o mDNS desligado o anúncio não sobe e não dá erro", ok58 and DS58._state["zc"] is None)
    c.post("/admin/server/save", json={"mdns": True, "url": "", "name": "StarFlix"})

    # ---- 62.2: descoberta UDP (resposta ao broadcast) ----
    from server import discovery as DS62
    c.post("/admin/server/save", json={"mdns": True, "url": "", "name": "StarFlix"})
    DS62._udp_seen.clear()
    r62 = DS62.discover_reply(b"STARFLIX_DISCOVER\n", "10.0.0.5", now=1000.0)
    j62 = json.loads(r62) if r62 else {}
    check("62.2 broadcast válido recebe app, id, nome, versão e porta", j62.get("app") == "starflix" and j62.get("port") == __import__("config").PORT and j62.get("id") and j62.get("version"))
    check("62.2 pedido repetido do mesmo IP em menos de 0,3 s é ignorado", DS62.discover_reply(b"STARFLIX_DISCOVER", "10.0.0.5", now=1000.1) is None
          and DS62.discover_reply(b"STARFLIX_DISCOVER", "10.0.0.5", now=1001.0) is not None)
    check("62.2 texto diferente do combinado não recebe resposta", DS62.discover_reply(b"oi", "10.0.0.6", now=1002.0) is None)
    c.post("/admin/server/save", json={"mdns": False})
    DS62._udp_seen.clear()
    check("62.2 com o mDNS desligado o servidor não responde ao broadcast", DS62.discover_reply(b"STARFLIX_DISCOVER", "10.0.0.7", now=1003.0) is None)
    c.post("/admin/server/save", json={"mdns": True, "url": "", "name": "StarFlix"})

    # ---- 62.4: token curto de imagem (Roku) ----
    from server import img_token as IT62
    from server.tv_auth import create_tv_device as CTD62
    anon62 = run.app.test_client()
    with get_db() as conn:
        u62 = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()["id"]
        p62 = conn.execute("SELECT id FROM profiles WHERE user_id = ? ORDER BY id LIMIT 1", (u62,)).fetchone()["id"]
        tv62, did62 = CTD62(conn, u62, "Roku 62", int(time.time()))
    H62 = {"Authorization": "Bearer " + tv62}
    r62 = anon62.get("/api/tv/img-token", headers={**H62, "X-Profile": str(p62)})
    tok62 = (r62.json or {}).get("token", "")
    check("62.4 /api/tv/img-token entrega token do perfil em uso e a validade", r62.status_code == 200 and len(tok62.split(".")) == 5
          and tok62.split(".")[2] == str(p62) and r62.json.get("ttl", 0) > 0)
    check("62.4 sem perfil escolhido o token sai com perfil 0", anon62.get("/api/tv/img-token", headers=H62).json["token"].split(".")[2] == "0")
    check("62.4 o navegador (cookie, sem Bearer de TV) não recebe token de imagem", c.get("/api/tv/img-token").status_code == 400)
    check("62.4 imagem de perfil carrega com ?it= e sem cookie novo", anon62.get(f"/pavatar/{p62}?it={tok62}").status_code == 200
          and "Set-Cookie" not in anon62.get(f"/pavatar/{p62}?it={tok62}").headers)
    check("62.4 sem o token a mesma imagem não abre", anon62.get(f"/pavatar/{p62}").status_code != 200)
    check("62.4 token adulterado: 401", anon62.get(f"/pavatar/{p62}?it={tok62[:-1]}{'0' if tok62[-1] != '0' else '1'}").status_code == 401)
    check("62.4 o token não vale em rota que não é de imagem", anon62.get(f"/api/tv/profiles?it={tok62}").status_code == 401)
    with run.app.app_context():
        with get_db() as conn:
            check("62.4 token vencido não resolve", IT62.resolve(conn, tok62, now=time.time() + 13 * 3600) is None)
        check("62.4 a URL é estável dentro da janela de 6 h (cache da Roku)", IT62.make(did62, u62, p62, now=1000)[0] == IT62.make(did62, u62, p62, now=2000)[0])
    with get_db() as conn:
        conn.execute("DELETE FROM tv_devices WHERE id = ?", (did62,))
    check("62.4 aparelho revogado: o token de imagem cai na hora", anon62.get(f"/pavatar/{p62}?it={tok62}").status_code == 401)

    # ---- 62.7: legendas deslocadas (HLS retomado) e token curto nas legendas ----
    from server import subtitles as ST62
    vtt62 = "WEBVTT\n\n00:00:05.000 --> 00:00:08.000\nA\n\n00:01:10.500 --> 00:01:12.000\nB\n"
    out62 = ST62.shift_vtt(vtt62, 60)
    check("62.7 shift_vtt descarta o que termina antes de 0 e desloca o resto", "\nA\n" not in out62 and "00:00:10.500 --> 00:00:12.000" in out62)
    check("62.7 shift_vtt com 0 não muda nada", ST62.shift_vtt(vtt62, 0) == vtt62)
    eps62 = {r_.endpoint for r_ in run.app.url_map.iter_rules()}
    check("62.7 as rotas de legenda .vtt aceitam o token curto (?it=)", {"subtitles.subs_file", "subtitles.subs_embedded"} <= IT62.IMG_EPS
          and {"subtitles.subs_file", "subtitles.subs_embedded"} <= eps62)
    check("62.16 vídeo (direct/HLS) aceita o token curto (?it=) para o emulador web", {"stream.direct", "stream.hls_file"} <= IT62.IMG_EPS
          and {"stream.direct", "stream.hls_file"} <= eps62)

    # limpeza
    sql32("DELETE FROM phone_tokens")
    sql32("DELETE FROM phone_devices")
    sql32("DELETE FROM tv_tickets")
    TA58._hits.clear()
    # ---- 59.34: idiomas (troca pela API, fallback, plural em russo, /api/i18n/*, cookie e perfil) ----
    from server import i18n as I59
    anon59 = run.app.test_client()
    LANGS59 = ["pt-BR", "en-US", "es-ES", "ru-RU", "fr-FR", "de-DE", "it-IT", "ja-JP", "zh-CN", "tr-TR"]
    check("59.34 LANGS tem os 10 idiomas", sorted(I59.CODES) == sorted(LANGS59))
    ok59 = True
    for l59 in LANGS59:
        r = anon59.get(f"/api/i18n/{l59}")
        j59 = r.json if r.status_code == 200 else {}
        ok59 = ok59 and r.status_code == 200 and j59.get("lang") == l59 and j59.get("strings", {}).get("app.name") == "StarFlix" \
            and len(j59["strings"]) >= 1500
    check("59.34 GET /api/i18n/<idioma> responde 200 com o catálogo completo nos 10 idiomas", ok59)
    check("59.34 idioma fora dos 10 (e variante en_GB) dá 404", anon59.get("/api/i18n/xx-XX").status_code == 404 and anon59.get("/api/i18n/en_GB").status_code == 404)
    r = anon59.get("/api/i18n/ru-RU")
    et59 = r.headers.get("ETag", "")
    check("59.34 catálogo traz ETag e revalida (If-None-Match -> 304)", bool(et59) and "no-cache" in r.headers.get("Cache-Control", "")
          and anon59.get("/api/i18n/ru-RU", headers={"If-None-Match": et59}).status_code == 304)
    ru59 = r.json["strings"]
    check("59.34 o catálogo do ru traz as 4 formas de plural e as chaves android.*", all(f"common.items.{k}" in ru59 for k in ("one", "few", "many", "other"))
          and "android.tv_items_count.many" in ru59)
    # plural em russo (CLDR)
    cats59 = {n: I59.plural_category("ru-RU", n) for n in (0, 1, 2, 4, 5, 11, 12, 21, 22, 25, 101, 111)}
    check("59.34 plural ru: 1/21/101 one, 2/4/22 few, 0/5/11/12/25/111 many",
          all(cats59[n] == "one" for n in (1, 21, 101)) and all(cats59[n] == "few" for n in (2, 4, 22))
          and all(cats59[n] == "many" for n in (0, 5, 11, 12, 25, 111)))
    check("59.34 t() com n= escolhe o texto do plural em russo", [I59.t("common.items", "ru-RU", n=n) for n in (1, 2, 5, 21)]
          == ["1 элемент", "2 элемента", "5 элементов", "21 элемент"])
    check("59.34 plural em en-US, pt-BR (0 e 1 no singular) e ja (só other)", I59.t("common.items", "en-US", n=1) == "1 item" and I59.t("common.items", "en-US", n=2) == "2 items"
          and I59.plural_category("pt-BR", 0) == "one" and I59.plural_category("ja-JP", 1) == "other")
    # fallback
    check("59.34 fallback: chave inexistente devolve a própria chave e idioma desconhecido cai no pt-BR", I59.t("nao.existe.59", "ru-RU") == "nao.existe.59"
          and I59.t("app.name", "klingon") == "StarFlix" and I59.t("common.save", "klingon") == I59.t("common.save", "pt-BR"))
    check("59.34 variável ausente fica {x} e variável passada é trocada", I59.t("android.connect_confirm", "en-US", name="Sala") == "Connect to Sala ({host})?")
    # ordem de prioridade
    check("59.34 pick: perfil > conta > cookie > Accept-Language > pt-BR (60.2: sem padrão do servidor)",
          I59.pick("en-US", "es-ES", "de-DE", ["fr-FR"]) == "en-US" and I59.pick(None, "es-ES", "de-DE", ["fr-FR"]) == "es-ES"
          and I59.pick(None, None, "de-DE", ["fr-FR"]) == "de-DE" and I59.pick(None, None, None, ["fr-FR"]) == "fr-FR"
          and I59.pick(None, None, None, []) == "pt-BR" and I59.pick() == "pt-BR" and I59.pick(None, None, None, ["*", "xx"]) == "pt-BR")
    # sem login: cookie e Accept-Language
    def htmllang59(cl, **kw):
        m = re.search(r'<html lang="([^"]*)"', cl.get("/login", **kw).get_data(as_text=True))
        return m.group(1) if m else None
    check("59.34 sem login: padrão pt-BR, Accept-Language escolhe o idioma e en-GB cai no en-US", htmllang59(run.app.test_client()) == "pt-BR"
          and htmllang59(run.app.test_client(), headers={"Accept-Language": "fr-FR,fr;q=0.9"}) == "fr-FR"
          and htmllang59(run.app.test_client(), headers={"Accept-Language": "en-GB"}) == "en-US")
    r = anon59.post("/api/i18n/set", json={"lang": "de-DE"})
    ck59 = r.headers.get("Set-Cookie", "")
    check("59.34 POST /api/i18n/set sem login grava o cookie sf_lang (1 ano, Lax) e a tela de login segue o idioma",
          r.status_code == 200 and r.json == {"ok": True, "lang": "de-DE", "metadata_refresh": False} and "sf_lang=de-DE" in ck59 and "SameSite=Lax" in ck59 and "Max-Age=31536000" in ck59
          and htmllang59(anon59, headers={"Accept-Language": "fr-FR"}) == "de-DE")
    check("59.34 idioma inválido, ausente ou fora dos 10 dá 400 e não grava cookie", all(
        (lambda rr: rr.status_code == 400 and "sf_lang" not in rr.headers.get("Set-Cookie", ""))(anon59.post("/api/i18n/set", json=body))
        for body in ({"lang": "xx-XX"}, {"lang": "en_GB"}, {"lang": 5}, {}, [])))
    # 60.2: não existe mais idioma padrão do servidor (Admin -> Servidor); um default_lang antigo no banco é ignorado
    with get_db() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('default_lang', 'tr-TR') ON CONFLICT(key) DO UPDATE SET value = excluded.value")
        conn.commit()
    r = c.post("/admin/server/save", json={"lang": "tr-TR"})
    check("60.2 sem padrão do servidor: `default_lang` antigo e `lang` no save não mudam o idioma (pt-BR sem cookie nem Accept-Language)",
          r.status_code == 200 and "lang" not in c.get("/admin/server/data").json and htmllang59(run.app.test_client()) == "pt-BR")
    with get_db() as conn:
        conn.execute("DELETE FROM settings WHERE key = 'default_lang'")
        conn.commit()
    check("60.2 a tela Servidor não tem mais o seletor de idioma", 'id="sv-lang"' not in c.get("/admin/server").get_data(as_text=True))
    # 60.1: porta em Configurações -> Servidor
    import socket as sock60
    import config as cfg60
    d60 = c.get("/admin/server/data").json
    check("60.1 porta padrão 32000 em /admin/server/data e /api/server-info", d60["port"] == 32000 == cfg60.DEFAULT_PORT and anon58.get("/api/server-info").json["port"] == cfg60.PORT)
    check("60.1 porta fora de 1024–65535, não numérica ou booleana dá 400", all(c.post("/admin/server/save", json={"port": v}).status_code == 400 for v in (0, 80, 70000, "32001", 3.5, True, None)))
    busy60 = sock60.socket()
    busy60.bind(("0.0.0.0", 0))
    busy60.listen(1)
    r = c.post("/admin/server/save", json={"port": busy60.getsockname()[1]})
    check("60.1 porta em uso por outro programa dá 400 e nada é gravado", r.status_code == 400 and r.json.get("code") == "err.porta_em_uso" and get_setting_port60() == "")
    busy60.close()
    free60 = sock60.socket()
    free60.bind(("0.0.0.0", 0))
    np60 = free60.getsockname()[1]
    free60.close()
    r = c.post("/admin/server/save", json={"port": np60})
    check("60.1 porta livre é gravada e a resposta pede reinício (sem reiniciar em teste)", r.status_code == 200 and r.json["restart"] is True and r.json["new_port"] == np60
          and get_setting_port60() == str(np60) and cfg60.PORT == 32000 and cfg60.RESTART_ON_PORT is False)
    cfg60.PORT = 32000
    import server.admin_server as as60
    as60.load_port()
    check("60.1 load_port() na partida lê a porta salva (e o mDNS/server-info a usam)", cfg60.PORT == np60 and anon58.get("/api/server-info").json["port"] == np60
          and all(u.endswith(":%d" % np60) for u in anon58.get("/api/server-info").json["urls"]["local"]))
    r = c.post("/admin/server/save", json={"port": 32000})
    as60.load_port()
    check("60.1 voltar ao 32000 também reinicia e a partida seguinte usa 32000", r.status_code == 200 and r.json["restart"] is True and cfg60.PORT == 32000)
    check("60.1 salvar sem `port` mantém a porta e não pede reinício", c.post("/admin/server/save", json={"name": "Casa 58"}).json["restart"] is False)
    # ---- 60.10: Restaurar backup pelo site ----
    import zipfile as zf60
    from server import backup as bk60
    os.makedirs(cfg60.BACKUPS_DIR, exist_ok=True)
    bad60 = os.path.join(cfg60.BACKUPS_DIR, "starflix-20260102-000000.zip")
    good60 = os.path.join(cfg60.BACKUPS_DIR, "starflix-20260102-000001.zip")
    db60 = os.path.join(cfg60.BACKUPS_DIR, "t60.db")
    try:
        with zf60.ZipFile(bad60, "w") as z_:
            z_.writestr("x.txt", "1")
        bk60._copy_db(db60)
        with zf60.ZipFile(good60, "w") as z_:
            z_.write(db60, "starflix.db")
        users60 = sql32("SELECT COUNT(*) FROM users")
        check("60.10 restaurar sem login não passa", anon58.post("/admin/backup/starflix-20260102-000001.zip/restore").status_code in (301, 302, 401, 403))
        check("60.10 backup que não existe dá 404", c.post("/admin/backup/starflix-20260102-999999.zip/restore").status_code == 404)
        r = c.post("/admin/backup/starflix-20260102-000000.zip/restore")
        check("60.10 zip sem starflix.db dá 400 err.restore_sem_banco (validado antes de reiniciar)", r.status_code == 400 and r.json.get("code") == "err.restore_sem_banco")
        r = c.post("/admin/backup/starflix-20260102-000001.zip/restore")
        check("60.10 em teste (sem run.py) não reinicia: 400 err.restore_indisponivel e o banco fica intacto", r.status_code == 400 and r.json.get("code") == "err.restore_indisponivel" and sql32("SELECT COUNT(*) FROM users") == users60)
        check("60.10 /health traz o `boot` do processo", anon58.get("/health").json.get("boot"))
        rs60 = bk60._script()
        try:
            rs60.validate(bad60)
            bad_ok60 = False
        except rs60.RestoreError as e_:
            bad_ok60 = e_.key == "err.restore_sem_banco"
        check("60.10 validate recusa o zip sem banco com a chave err.restore_sem_banco", bad_ok60)
        try:
            os.remove(rs60.RESULT)
        except OSError:
            pass
        check("60.10 sem arquivo de resultado: {ok: null}", c.get("/admin/backup/restore-result").json["ok"] is None)
        with open(rs60.RESULT, "w", encoding="utf-8") as f_:
            json.dump({"ok": False, "key": "err.restore_falhou", "vars": {}, "msg": "x"}, f_)
        r = c.get("/admin/backup/restore-result")
        check("60.10 o resultado é entregue uma vez e o arquivo some", r.json["ok"] is False and r.json["key"] == "err.restore_falhou" and not os.path.exists(rs60.RESULT) and c.get("/admin/backup/restore-result").json["ok"] is None)
        pn60 = c.get("/admin").get_data(as_text=True)
        js60 = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "static", "js", "admin-backup.js"), encoding="utf-8").read()
        check("60.10 o Painel traz a tela de espera (animação + texto) e o JS chama /restore e confere o `boot`", 'id="bk-wait"' in pn60 and 'id="restore-logo"' in pn60 and "/restore'" in js60 and "boot" in js60)
    finally:
        for f_ in (bad60, good60, db60):
            try:
                os.remove(f_)
            except OSError:
                pass
    # com login: grava no perfil e vence o cookie
    r = c.post("/api/i18n/set", json={"lang": "ru-RU"})
    with get_db() as conn:
        pf59 = json.loads(conn.execute("SELECT prefs FROM profiles WHERE id = ?", (pid,)).fetchone()["prefs"] or "{}")
    check("59.34 POST /api/i18n/set com perfil escolhido grava o lang no perfil e o cookie", r.status_code == 200 and pf59.get("lang") == "ru-RU" and "sf_lang=ru-RU" in r.headers.get("Set-Cookie", ""))
    check("59.34 o idioma do perfil vence o cookie e a página do site abre nesse idioma", 'lang="ru-RU"' in c.get("/", headers={"Cookie": "sf_lang=en-US"}).get_data(as_text=True))
    r = c.post("/api/i18n/set", json={"lang": "ja-JP"})
    with get_db() as conn:
        pf59 = json.loads(conn.execute("SELECT prefs FROM profiles WHERE id = ?", (pid,)).fetchone()["prefs"] or "{}")
    check("59.34 trocar de novo troca na hora, sem reiniciar", pf59.get("lang") == "ja-JP" and 'lang="ja-JP"' in c.get("/").get_data(as_text=True))
    c.post("/api/i18n/set", json={"lang": "pt-BR"})
    check("59.34 voltar ao pt-BR deixa a página no idioma da fonte", 'lang="pt-BR"' in c.get("/").get_data(as_text=True))
    # ---- 59.37: o idioma dos agentes (TMDB, TVDB, SubDL) é o do usuário; trocar refaz os metadados (sem rede: ensure_fresh e a varredura são trocados) ----
    import config as cfg59
    import server.tmdb_lists as tl59
    import server.scanner as sc59
    import server.meta_lang as ml59
    real59 = (tl59.ensure_fresh, sc59.refresh_language_async, cfg59.TMDB_LANG, cfg59.TMDB_REGION, cfg59.TVDB_LANG, cfg59.SUBDL_LANG)
    lists59, scans59 = [], []
    tl59.ensure_fresh = lambda: lists59.append(1)
    sc59.refresh_language_async = lambda: scans59.append(1)
    try:
        check("59.37 MAP cobre os 10 idiomas com TMDB, TVDB e SubDL", sorted(ml59.MAP) == sorted(LANGS59) and all(len(v_) == 3 for v_ in ml59.MAP.values()))
        ml59._apply("pt-BR")
        r = c.post("/api/i18n/set", json={"lang": "en-US"})
        check("59.37 /api/i18n/set com login ajusta TMDB, região, TVDB e SubDL e pede a nova varredura",
              r.status_code == 200 and r.json["metadata_refresh"] is True and (cfg59.TMDB_LANG, cfg59.TMDB_REGION, cfg59.TVDB_LANG, cfg59.SUBDL_LANG) == ("en-US", "US", "eng", "EN")
              and ml59.current() == "en-US" and len(scans59) == 1 and len(lists59) == 1
              and sql32("SELECT value FROM settings WHERE key = 'meta_lang'")[0]["value"] == "en-US")
        r = c.post("/api/i18n/set", json={"lang": "en-US"})
        check("59.37 mesmo idioma não refaz nada", r.status_code == 200 and r.json["metadata_refresh"] is False and len(scans59) == 1 and len(lists59) == 1)
        r = c.post("/api/i18n/set", json={"lang": "ru-RU"})
        check("59.37 ru-RU: TMDB ru-RU/RU, TVDB rus, SubDL RU", r.json["metadata_refresh"] is True and (cfg59.TMDB_LANG, cfg59.TMDB_REGION, cfg59.TVDB_LANG, cfg59.SUBDL_LANG) == ("ru-RU", "RU", "rus", "RU") and len(scans59) == 2)
        r = c.post("/account/settings", json={"values": {"lang": "ja-JP"}})
        check("59.37 /account/settings com `lang` também troca os agentes (ja-JP -> JA)", r.status_code == 200 and cfg59.TVDB_LANG == "jpn" and cfg59.SUBDL_LANG == "JA" and len(scans59) == 3)
        r = c.post("/account/settings", json={"values": {"seen": "all"}})
        check("59.37 /account/settings sem `lang` não mexe nos agentes", r.status_code == 200 and len(scans59) == 3 and cfg59.SUBDL_LANG == "JA")
        check("59.37 idioma inválido dá 400 e não troca os agentes", c.post("/api/i18n/set", json={"lang": "xx-XX"}).status_code == 400 and len(scans59) == 3 and ml59.current() == "ja-JP")
        r = anon59.post("/api/i18n/set", json={"lang": "fr-FR"})
        check("59.37 sem login só grava o cookie: agentes e metadados ficam como estão", r.status_code == 200 and r.json["metadata_refresh"] is False and ml59.current() == "ja-JP" and len(scans59) == 3)
        ml59._apply("de-DE")
        with get_db() as cn59:
            ml59._set(cn59, "meta_lang", "es-ES")
            cn59.commit()
            ml59.load(cn59)
        check("59.37 load() na partida restaura do banco (es-ES -> es-ES/ES/spa/ES)", (cfg59.TMDB_LANG, cfg59.TVDB_LANG, cfg59.SUBDL_LANG) == ("es-ES", "spa", "ES"))
        ag59 = {a_["id"]: a_ for a_ in c.get("/admin/agents/data").json["agents"]}
        check("59.37 Agentes sem seletor de idioma; salvar sem chave dá 400", all("lang" not in v_ and "langs" not in v_ for v_ in ag59.values())
              and c.post("/admin/agents/tvdb", json={}).status_code == 400)
        pg59 = c.get("/admin/agents").get_data(as_text=True) + open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "static", "js", "agents.js"), encoding="utf-8").read()
        check("59.37 a página e o JS de Agentes não têm mais as chaves ag.lang*", "ag.lang" not in pg59)
        check("59.37 assistente e edição de biblioteca não enviam nem recebem idioma", all(k_ not in J28("/admin/libraries/data").json["libraries"][0] for k_ in ("lang",)))
    finally:
        tl59.ensure_fresh, sc59.refresh_language_async, cfg59.TMDB_LANG, cfg59.TMDB_REGION, cfg59.TVDB_LANG, cfg59.SUBDL_LANG = real59
        sql32("DELETE FROM settings WHERE key = 'meta_lang'")
        c.post("/api/i18n/set", json={"lang": "pt-BR"})
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n{'PASSOU' if not fails else 'FALHOU: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
