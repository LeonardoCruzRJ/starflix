"""Perfil de capacidades do cliente (52.1): o site e o app dizem o que o aparelho decodifica; o servidor só aceita valores de listas conhecidas.
Forma compacta em `?caps=`, ex.: `v=h264.hevc&a=aac.ac3&c=mp4.mkv&b10=1&hdr=0&ch=6`. Sem `caps` o servidor se comporta como antes (None)."""
from urllib.parse import quote

VIDEO = ("h264", "hevc", "av1", "vp9", "vp8")
AUDIO = ("aac", "mp3", "opus", "vorbis", "flac", "ac3", "eac3")
CONTAINERS = ("mp4", "mkv", "webm", "ts")
CHANNELS = (2, 6, 8)


class Caps:
    def __init__(self, v=(), a=(), c=(), b10=False, hdr=False, ch=2):
        self.v, self.a, self.c = frozenset(v), frozenset(a), frozenset(c)
        self.b10, self.hdr, self.ch = bool(b10), bool(hdr), ch

    def query(self):
        """Forma compacta (ordem fixa) para repassar nas URLs de direct play."""
        j = lambda xs, order: ".".join(x for x in order if x in xs)
        return (f"v={j(self.v, VIDEO)}&a={j(self.a, AUDIO)}&c={j(self.c, CONTAINERS)}"
                f"&b10={int(self.b10)}&hdr={int(self.hdr)}&ch={self.ch}")

    def param(self):
        return "caps=" + quote(self.query(), safe="")

    def __eq__(self, o):
        return isinstance(o, Caps) and self.query() == o.query()


def parse_caps(args):
    """`Caps` a partir de `args.get("caps")` (lista branca; valor desconhecido é ignorado); None se não veio ou veio vazio/inválido."""
    raw = (args.get("caps") or "").strip()
    if not raw or len(raw) > 300:
        return None
    kv = {}
    for part in raw.split("&"):
        k, _, v = part.partition("=")
        if k in ("v", "a", "c", "b10", "hdr", "ch"):
            kv[k] = v
    if not kv:
        return None
    pick = lambda k, allowed: [x for x in kv.get(k, "").split(".") if x in allowed]
    try:
        ch = int(kv.get("ch", 2))
    except ValueError:
        ch = 2
    return Caps(pick("v", VIDEO), pick("a", AUDIO), pick("c", CONTAINERS), kv.get("b10") == "1", kv.get("hdr") == "1", ch if ch in CHANNELS else 2)
