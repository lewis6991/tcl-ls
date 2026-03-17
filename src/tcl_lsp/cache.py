from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from threading import RLock
from typing import ParamSpec, TypeVar, cast

P = ParamSpec('P')
R = TypeVar('R')

_CACHE_CLEARERS: dict[str, list[Callable[[], None]]] = {}
_CACHE_LOCK = RLock()


def registered_lru_cache(
    *,
    group: str,
    maxsize: int | None = 128,
    typed: bool = False,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorator(function: Callable[P, R]) -> Callable[P, R]:
        cached = lru_cache(maxsize=maxsize, typed=typed)(function)
        with _CACHE_LOCK:
            _CACHE_CLEARERS.setdefault(group, []).append(cached.cache_clear)
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
