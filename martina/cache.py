"""A small, bounded result cache keyed by data version.

Views are pure functions of (data version, filters, options), so a result can
be reused until the next refresh. Old versions fall out by themselves.
"""
import threading
from collections import OrderedDict


class ResultCache:
    def __init__(self, size=256):
        self.size = size
        self.items = OrderedDict()
        self.lock = threading.Lock()
        self.hits = self.misses = 0

    def get(self, key, build):
        with self.lock:
            if key in self.items:
                self.items.move_to_end(key)
                self.hits += 1
                return self.items[key]
        value = build()                       # built outside the lock
        with self.lock:
            self.misses += 1
            self.items[key] = value
            self.items.move_to_end(key)
            while len(self.items) > self.size:
                self.items.popitem(last=False)
        return value

    def clear(self):
        with self.lock:
            self.items.clear()


VIEWS = ResultCache(512)


def cached(name):
    """Decorator: cache a view function on (STORE.version, name, args)."""
    def wrap(fn):
        def inner(*args):
            from .data.store import STORE
            STORE.ensure()
            key = (STORE.version, name) + tuple(_hashable(a) for a in args)
            return VIEWS.get(key, lambda: fn(*args))
        inner.__name__ = fn.__name__
        inner.__doc__ = fn.__doc__
        inner.uncached = fn
        return inner
    return wrap


def _hashable(v):
    if isinstance(v, (list, set)):
        return tuple(_hashable(x) for x in v)
    if isinstance(v, dict):
        return tuple(sorted((k, _hashable(x)) for k, x in v.items()))
    return v
