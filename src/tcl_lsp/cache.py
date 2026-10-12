from __future__ import annotations

from collections.abc import Callable, Hashable
from functools import lru_cache
from threading import RLock
from typing import ParamSpec, Self, TypeVar, cast

P = ParamSpec('P')
R = TypeVar('R')

_CACHE_CLEARERS: dict[str, list[Callable[[], None]]] = {}
_CACHE_LOCK = RLock()


class VersionCache[K: Hashable, V]:
    """Read the previous version; retain only results used by this version.

    Callers put both computed and reused results. Forks copy those entries,
    without retaining a chain of caches or changing the published version.
    Values must be immutable.
    """

    def __init__(self) -> None:
        self._previous: dict[K, V] = {}
        self._current: dict[K, V] = {}
        self._lock = RLock()

    def fork(self) -> Self:
        result = type(self)()
        with self._lock:
            result._previous = self._current.copy()
        return result

    def get(self, key: K) -> V | None:
        with self._lock:
            return self._current.get(key, self._previous.get(key))

    def put(self, key: K, value: V) -> None:
        with self._lock:
            self._current[key] = value


def register_cache_clearer(group: str, clear: Callable[[], None]) -> None:
    with _CACHE_LOCK:
        _CACHE_CLEARERS.setdefault(group, []).append(clear)


def registered_lru_cache(
    *,
    group: str,
    maxsize: int | None = 128,
    typed: bool = False,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorator(function: Callable[P, R]) -> Callable[P, R]:
        cached = lru_cache(maxsize=maxsize, typed=typed)(function)
        register_cache_clearer(group, cached.cache_clear)
        return cast(Callable[P, R], cached)

    return decorator


def metadata_lru_cache(
    *,
    maxsize: int | None = 128,
    typed: bool = False,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    return registered_lru_cache(group='metadata', maxsize=maxsize, typed=typed)


def clear_cache_group(group: str) -> None:
    with _CACHE_LOCK:
        clearers = tuple(_CACHE_CLEARERS.get(group, ()))
    for clearer in clearers:
        clearer()
