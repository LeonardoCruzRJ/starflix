"""62.4: token curto de imagem para apps que não conseguem mandar cabeçalho ao carregar capas (o `Poster` da Roku).
Formato `<aparelho>.<usuário>.<perfil>.<validade>.<assinatura>` (HMAC-SHA256 com a chave secreta do servidor). A URL fica a mesma durante
uma janela de 6 h (o cache de imagens do aparelho funciona) e vale de 6 a 12 h. Só serve em `GET`/`HEAD` das rotas de imagem e das legendas .vtt (`IMG_EPS`,
conferidas em `gate()`); aparelho apagado (Revogar) ou perfil removido invalida na hora. Nunca substitui o Bearer em outras rotas."""
import hashlib
import hmac
import time

from flask import current_app

WINDOW = 6 * 3600
IMG_EPS = frozenset({"libraries.poster", "images.backdrop", "images.logo", "images.person", "images.still", "images.thumb",
                     "collections.poster", "playlists.image", "people.person_art", "account.pavatar",
                     "subtitles.subs_file", "subtitles.subs_embedded",
                     "stream.direct", "stream.hls_file"})  # 62.7: legendas .vtt (a Roku busca sem cabeçalho); 62.16: vídeo (direct/HLS) para o emulador web, cujo <video> não envia HttpHeaders


def _sig(did, uid, pid, exp):
    key = current_app.secret_key
    key = key.encode("utf-8") if isinstance(key, str) else key
    return hmac.new(key, f"img|{did}|{uid}|{pid}|{exp}".encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def make(did, uid, pid, now=None):
    """(token, segundos de validade). `pid` 0 = ainda sem perfil escolhido."""
    now = int(time.time() if now is None else now)
    exp = (now // WINDOW + 2) * WINDOW
    pid = int(pid or 0)
    return f"{did}.{uid}.{pid}.{exp}.{_sig(did, uid, pid, exp)}", exp - now


def resolve(conn, tok, now=None):
    """Dados para montar a sessão da TV ({device_id, user_id, session_ver, profile_id}) ou None (assinatura errada, vencido, aparelho/perfil sumiu)."""
    parts = str(tok or "").split(".")
    if len(parts) != 5 or not all(p.isdigit() for p in parts[:4]) or len(tok) > 200:
        return None
    did, uid, pid, exp = (int(p) for p in parts[:4])
    if int(time.time() if now is None else now) >= exp or not hmac.compare_digest(parts[4], _sig(did, uid, pid, exp)):
        return None
    d = conn.execute("SELECT d.id, u.session_ver FROM tv_devices d JOIN users u ON u.id = d.user_id WHERE d.id = ? AND d.user_id = ?", (did, uid)).fetchone()
    if not d:
        return None
    if pid and not conn.execute("SELECT 1 FROM profiles WHERE id = ? AND user_id = ?", (pid, uid)).fetchone():
        return None
    return {"device_id": d["id"], "user_id": uid, "session_ver": d["session_ver"] or 0, "profile_id": pid or None}
