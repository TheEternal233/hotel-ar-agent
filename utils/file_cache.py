import os
import threading
import time
from functools import wraps

_CACHE_TTL = 300

_cache = {}
_cache_lock = threading.Lock()


def _cleanup_expired():
    now = time.time()
    expired = [k for k, (_, t) in _cache.items() if now - t > _CACHE_TTL]
    for k in expired:
        del _cache[k]


def file_cache(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not args:
            return func(*args, **kwargs)

        file_path = args[0]
        if not isinstance(file_path, str) or not os.path.isfile(file_path):
            return func(*args, **kwargs)

        if kwargs.get("wb") is not None:
            return func(*args, **kwargs)

        mtime = os.path.getmtime(file_path)
        cache_kwargs = {k: v for k, v in kwargs.items() if k != "wb"}
        cache_key = (
            func.__name__,
            file_path,
            mtime,
            args[1:],
            tuple(sorted(cache_kwargs.items())),
        )

        with _cache_lock:
            entry = _cache.get(cache_key)
            if entry is not None:
                result, cached_time = entry
                if time.time() - cached_time < _CACHE_TTL:
                    return result

        result = func(*args, **kwargs)

        with _cache_lock:
            _cache[cache_key] = (result, time.time())
            _cleanup_expired()

        return result

    return wrapper


def clear_cache():
    with _cache_lock:
        _cache.clear()