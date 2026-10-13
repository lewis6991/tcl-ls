from __future__ import annotations

from collections.abc import Callable

from tcl_lsp.analysis.facts.parsing import ListItem
from tcl_lsp.parser import word_static_text
from tcl_lsp.parser.model import BracedWord, VariableSubstitution, Word

type VariableSource = Callable[[str], ListItem | None]


def resolve_word_source(word: Word, variable_source: VariableSource) -> ListItem | None:
    """Resolve a literal or whole-variable Tcl word with its original location."""
    if word.expanded:
        return None
    if isinstance(word, BracedWord):
        text = word.raw_text[1:-1]
    else:
        text = word_static_text(word)
        if text is None:
            if len(word.parts) == 1 and isinstance(word.parts[0], VariableSubstitution):
                return variable_source(word.parts[0].name)
            return None
        # Decoded escapes need a source map; do not invent contiguous locations.
        if word.content_span.start.advance(text) != word.content_span.end:
            return None
    return ListItem(text=text, span=word.content_span, content_start=word.content_span.start)
