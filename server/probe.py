import json
import os
import re
import subprocess

from server import markers, scanstate
from server.db import get_db, hdr_label  # noqa: F401 (hdr_label vive em db.py para não criar ciclo)


def derive_hdr(v):
    """50.1: `none` | `hdr10` | `hlg` | `dv5` | `dv8` a partir dos campos de cor do vídeo (HDR10+ conta como hdr10)."""
    v = v or {}
    dv = v.get("dv_profile")
    if dv is not None:
        return "dv5" if dv == 5 else "dv8"  # 7/8/etc. têm camada base HDR10/HLG e convertem normal
    t = (v.get("color_transfer") or "").lower()
    if t == "smpte2084":
        return "hdr10"
    if t == "arib-std-b67":
        return "hlg"
    return "none"


def _bits(s):
    try:
        return int(s.get("bits_per_raw_sample"))
    except (TypeError, ValueError):
        m = re.search(r"(\d+)(?:le|be)?$", s.get("pix_fmt") or "")
        return int(m.group(1)) if m and int(m.group(1)) in (9, 10, 12, 14, 16) else 8


def probe(path):
    """Roda ffprobe e devolve dict com duração, vídeo, áudios e legendas. None se falhar."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", "-show_chapters", path],
        capture_output=True, text=True, timeout=60,
    )
    if out.returncode != 0:
        return None
    data = json.loads(out.stdout)
    info = {
        "duration": float(data.get("format", {}).get("duration") or 0),
        "container": data.get("format", {}).get("format_name"),
        "video": None,
        "audio": [],
        "subs": [],
        "chapters": [  # 48.1: capítulos (alimentam os marcadores de abertura/créditos)
            {"start": float(c.get("start_time") or 0), "end": float(c.get("end_time") or 0), "title": (c.get("tags") or {}).get("title")}
            for c in data.get("chapters", [])
        ],
    }
    for s in data.get("streams", []):
        tags = s.get("tags", {})
        kind = s.get("codec_type")
        if kind == "video" and not info["video"] and not s.get("disposition", {}).get("attached_pic"):
            info["video"] = {"codec": s.get("codec_name"), "width": s.get("width"), "height": s.get("height"),
                             "pix_fmt": s.get("pix_fmt"), "color_transfer": s.get("color_transfer"),  # 50.1
                             "color_primaries": s.get("color_primaries"), "color_space": s.get("color_space"), "bits": _bits(s)}
            for sd in s.get("side_data_list") or []:
                if "DOVI" in str(sd.get("side_data_type", "")).upper() and sd.get("dv_profile") is not None:
                    info["video"]["dv_profile"] = int(sd["dv_profile"])
            info["video"]["hdr"] = derive_hdr(info["video"])
        elif kind == "audio":
            info["audio"].append({
                "index": s["index"], "codec": s.get("codec_name"), "channels": s.get("channels"),
                "lang": tags.get("language"), "title": tags.get("title"),
            })
        elif kind == "subtitle":
            info["subs"].append({
                "index": s["index"], "codec": s.get("codec_name"),
                "lang": tags.get("language"), "title": tags.get("title"),
            })
    return info


def _sig(path):
    """(tamanho, mtime) do arquivo, ou None se não existir."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_size, int(st.st_mtime))


def _same_error(raw, sig):
    """True se `raw` é um erro gravado para este mesmo tamanho/mtime."""
    if not raw:
        return False
    try:
        d = json.loads(raw)
    except ValueError:
        return False
    return bool(d.get("error")) and d.get("size") == sig[0] and d.get("mtime") == sig[1]


def probe_library(library_id, media_id=None):
    """Preenche `info` dos filmes/episódios da biblioteca que ainda não foram analisados (media_id restringe a um item)."""
    done = 0
    with get_db() as conn:
        items = [
            ("media", r["id"], r["path"], r["info"], r["id"])
            for r in conn.execute(
                "SELECT id, path, info FROM media WHERE library_id = ? AND path IS NOT NULL AND (info IS NULL OR (info NOT LIKE '%\"video\": null%' AND (info NOT LIKE '%pix_fmt%' OR info NOT LIKE '%color_transfer%'))) AND (? IS NULL OR id = ?)",
                (library_id, media_id, media_id),
            )
        ] + [
            ("episodes", r["id"], r["path"], r["info"], r["media_id"])
            for r in conn.execute(
                "SELECT e.id, e.path, e.info, e.media_id FROM episodes e JOIN media m ON m.id = e.media_id "
                "WHERE m.library_id = ? AND (e.info IS NULL OR (e.info NOT LIKE '%\"video\": null%' AND (e.info NOT LIKE '%pix_fmt%' OR e.info NOT LIKE '%color_transfer%'))) AND (? IS NULL OR m.id = ?)",
                (library_id, media_id, media_id),
            )
        ]
        cache = {}  # arquivo de vários episódios aparece em várias linhas: sonda uma vez só
        for table, id_, path, old_info, mid in items:
            if path in cache:
                info = cache[path]
                sig = _sig(path)
            else:
                sig = _sig(path)
                if sig is None:
                    continue
                if _same_error(old_info, sig):
                    cache[path] = False
                    continue  # erro já gravado e arquivo não mudou (tamanho/mtime)
                scanstate.set_current(mid)  # 35.14: só o item realmente analisado ganha o ícone
                try:
                    info = probe(path)
                except FileNotFoundError:  # ffprobe não instalado
                    return done
                except (subprocess.TimeoutExpired, OSError):
                    continue  # falha passageira (NAS lento/indisponível): não grava erro, tenta no próximo scan
                except Exception:
                    info = None
                cache[path] = info
            if info is False:
                continue
            conn.execute(
                f"UPDATE {table} SET info = ? WHERE id = ?",
                (json.dumps(info if info else {"error": True, "size": sig[0], "mtime": sig[1]}), id_),
            )
            if table == "episodes" and info:
                markers.sync_episode(conn, id_, info)
            conn.commit()  # sem transação aberta durante o próximo ffprobe
            done += 1
    return done
