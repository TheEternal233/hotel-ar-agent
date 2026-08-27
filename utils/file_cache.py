import os
import threading
import time
from functools import wraps
from collections import OrderedDict

_CACHE_TTL = 300
_CACHE_MAX_SIZE = 128  # 最大缓存条目数，防止 OOM

_cache = OrderedDict()
_cache_lock = threading.Lock()


def _cleanup_expired():
    """清理过期条目，同时检查总大小并在超限时淘汰最久未使用的条目。"""
    now = time.time()
    expired = [k for k, (_, t) in _cache.items() if now - t > _CACHE_TTL]
    for k in expired:
        del _cache[k]

    # LRU 淘汰：如果仍超出上限，移除最久未使用的条目
    while len(_cache) > _CACHE_MAX_SIZE:
        _cache.popitem(last=False)


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
                    # 命中缓存，移到末尾标记为最近使用
                    _cache.move_to_end(cache_key)
                    return result
                # 已过期，删除
                del _cache[cache_key]

        result = func(*args, **kwargs)

        with _cache_lock:
            # 写入新条目（如果已存在会更新并移到末尾）
            _cache[cache_key] = (result, time.time())
            _cache.move_to_end(cache_key)
            _cleanup_expired()

        return result

    return wrapper


def clear_cache():
    with _cache_lock:
        _cache.clear()