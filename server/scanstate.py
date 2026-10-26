"""35.8/35.9: itens que o exame está processando agora (ícone girando) e os já concluídos (capa atualizada na hora)."""
import threading
from collections import deque

_lock = threading.Lock()
_ids = set()
_done = deque(maxlen=500)  # (seq, id) dos itens que saíram do processamento
_seq = 0
_manual = set()  # 35.16: itens em tarefa avulsa (Corrigir Correspondência), fora do exame
_cancel = set()  # 35.22: bibliotecas apagadas durante o exame; o exame delas para no próximo item
_lib = None  # biblioteca que o exame está processando agora


class ScanCancelled(Exception):
    """A biblioteca em exame foi apagada: o exame dela termina."""


def _finish(old, keep=()):
    global _seq
    for i in sorted(old - set(keep)):
        _seq += 1
        _done.append((_seq, i))


def set_current(*ids):
    with _lock:
        new = {i for i in ids if i}
        if new and _lib is not None and _lib in _cancel:
            raise ScanCancelled()
        _finish(_ids, new)
        _ids.clear()
        _ids.update(new)


def clear():
    set_current()


def manual_start(i):
    with _lock:
        _manual.add(i)


def manual_end(i):
    with _lock:
        _manual.discard(i)
        _ids.discard(i)  # 35.17: o download do pôster marca o item como "atual"; ao fim da tarefa ele sempre conclui
        _finish({i})


def busy():
    with _lock:
        return bool(_manual)


def snapshot():
    with _lock:
        return sorted(_ids | _manual)


def done_since(since):
    """(seq atual, ids concluídos depois de `since`); since=None só devolve o seq."""
    with _lock:
        return _seq, ([] if since is None else sorted({i for s, i in _done if s > since}))


def set_lib(lid):
    """Biblioteca em exame (None = nenhuma); levanta ScanCancelled se ela já foi apagada."""
    global _lib
    with _lock:
        _lib = lid
        if lid is not None and lid in _cancel:
            raise ScanCancelled()


def cancel(lid):
    with _lock:
        _cancel.add(lid)


def cancelled(lid):
    with _lock:
        return lid in _cancel


def reset(lid=None):
    """Fim do exame da biblioteca `lid` (ou de todos, sem argumento): limpa o cancelamento."""
    global _lib
    with _lock:
        _lib = None
        if lid is None:
            _cancel.clear()
        else:
            _cancel.discard(lid)
