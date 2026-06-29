"""Tiny in-process store for reports so GET /report/{id} can retrieve them.

Bounded LRU-ish dict; the service is a thin convenience over the gate, not a
durable record. Persistent storage (if wanted) belongs in the app's database.
"""

import threading
from collections import OrderedDict

_LOCK = threading.Lock()
_STORE = OrderedDict()
_MAX = 256
_COUNTER = [0]


def put(report_dict):
    with _LOCK:
        _COUNTER[0] += 1
        rid = f"r{_COUNTER[0]:06d}"
        _STORE[rid] = report_dict
        while len(_STORE) > _MAX:
            _STORE.popitem(last=False)
        return rid


def get(rid):
    with _LOCK:
        return _STORE.get(rid)
