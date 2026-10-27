from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from tcl_lsp.parser import word_static_text
from tcl_lsp.parser.model import Word

type LayoutIssue = tuple[int, str]
type LayoutCache[T] = dict[int, tuple[tuple[Word, ...], T]]


@dataclass(frozen=True, slots=True)
class IfLayout:
    clauses: tuple[tuple[int, int | None], ...]
    else_body_index: int | None
    issue: LayoutIssue | None

    def body_word_indices(self) -> frozenset[int]:
        indices = {body for _, body in self.clauses if body is not None}
        if self.else_body_index is not None:
            indices.add(self.else_body_index)
        return frozenset(indices)


@dataclass(frozen=True, slots=True)
class TryLayout:
    handler_body_indices: tuple[int, ...]
    finally_body_index: int | None

    def body_word_indices(self) -> frozenset[int]:
        indices = {1, *self.handler_body_indices}
        if self.finally_body_index is not None:
            indices.add(self.finally_body_index)
        return frozenset(indices)


@dataclass(frozen=True, slots=True)
class SwitchOptions:
    value_index: int
    match_mode: str
    nocase: bool
    regexp_binding_words: tuple[Word, ...]
    issue: LayoutIssue | None = None


class CommandLayouts:
    """Reuse argument layouts within one document version.

    Keep the words beside each result so an identity key cannot be reused.
    Layouts describe argument positions even when a body is dynamic.
    """

    def __init__(self) -> None:
        self._ifs: LayoutCache[IfLayout] = {}
        self._tries: LayoutCache[TryLayout] = {}
        self._switches: LayoutCache[SwitchOptions] = {}

    def if_layout(self, words: tuple[Word, ...]) -> IfLayout:
        return _cached_layout(self._ifs, words, _if_layout)

    def try_layout(self, words: tuple[Word, ...]) -> TryLayout:
        return _cached_layout(self._tries, words, _try_layout)

    def switch_options(self, words: tuple[Word, ...]) -> SwitchOptions:
        return _cached_layout(self._switches, words, switch_options)


def _cached_layout[T](
    cache: LayoutCache[T], words: tuple[Word, ...], parse: Callable[[tuple[Word, ...]], T]
) -> T:
    key = id(words)
    cached = cache.get(key)
    if cached is None:
        result = parse(words)
        cache[key] = (words, result)
        return result
    return cached[1]


def _if_layout(words: tuple[Word, ...]) -> IfLayout:
    clauses: list[tuple[int, int | None]] = []
    else_body_index: int | None = None
    issue: LayoutIssue | None = None
    index = 1
    while index < len(words):
        clause_index = index
        if clauses:
            keyword = word_static_text(words[index])
            if keyword == 'elseif':
                index += 1
            elif keyword == 'else':
                if index + 1 >= len(words):
                    issue = (index, 'Malformed `if` command; `else` requires a body.')
                else:
                    else_body_index = index + 1
                    if index + 2 < len(words):
                        issue = (
                            index + 2,
                            'Malformed `if` command; trailing words after `else` body.',
                        )
                break
            else:
                if keyword is not None:
                    issue = (
                        index,
                        f'Malformed `if` command; expected `elseif` or `else`, got `{keyword}`.',
                    )
                break

        body_index = index + 1
        if body_index < len(words) and word_static_text(words[body_index]) == 'then':
            body_index += 1
        if body_index >= len(words):
            # Lowering still visits the condition of an incomplete clause.
            if clauses:
                issue = (
                    clause_index,
                    'Malformed `if` command; `elseif` requires a test and body.',
                )
            clauses.append((index, None))
            break
        clauses.append((index, body_index))
        index = body_index + 1
    return IfLayout(tuple(clauses), else_body_index, issue)


def _try_layout(words: tuple[Word, ...]) -> TryLayout:
    handlers: list[int] = []
    finally_body_index: int | None = None
    index = 2
    while index < len(words):
        clause_word = words[index]
        if clause_word.expanded:
            break
        clause_name = word_static_text(clause_word)
        if clause_name == 'finally':
            if index + 1 < len(words):
                finally_body_index = index + 1
            break
        if clause_name not in {'on', 'trap'} or index + 3 >= len(words):
            break
        if any(words[offset].expanded for offset in range(index, index + 4)):
            break
        handlers.append(index + 3)
        index += 4
    return TryLayout(tuple(handlers), finally_body_index)


def switch_options(words: tuple[Word, ...]) -> SwitchOptions:
    index = 1
    match_mode = 'exact'
    nocase = False
    bindings: list[Word] = []
    issue: LayoutIssue | None = None
    while index < len(words):
        option = word_static_text(words[index])
        if option is None:
            break
        if option == '--':
            index += 1
            break
        if option in {'-exact', '-glob', '-regexp'}:
            match_mode = option[1:]
            index += 1
            continue
        if option == '-nocase':
            nocase = True
            index += 1
            continue
        if option in {'-matchvar', '-indexvar'}:
            if index + 1 >= len(words):
                issue = (index, f'Malformed `switch` command; `{option}` requires a value.')
                break
            if match_mode == 'regexp':
                bindings.append(words[index + 1])
            index += 2
            continue
        if option.startswith('-') and option != '-':
            issue = (index, f'Malformed `switch` command; unknown option `{option}`.')
        break
    return SwitchOptions(index, match_mode, nocase, tuple(bindings), issue)
