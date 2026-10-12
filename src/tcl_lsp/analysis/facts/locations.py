from tcl_lsp.common import Position, Span


class SourceRelocation:
    """Map locations in unchanged text from one origin to another."""

    def __init__(self, before: Position, after: Position) -> None:
        self._before = before
        self._after = after
        self._positions: dict[Position, Position] = {}
        self._spans: dict[Span, Span] = {}

    def position(self, position: Position) -> Position:
        result = self._positions.get(position)
        if result is None:
            result = Position(
                position.offset + self._after.offset - self._before.offset,
                position.line + self._after.line - self._before.line,
                position.character
                + (
                    self._after.character - self._before.character
                    if position.line == self._before.line
                    else 0
                ),
            )
            self._positions[position] = result
        return result

    def span(self, span: Span) -> Span:
        result = self._spans.get(span)
        if result is None:
            result = Span(self.position(span.start), self.position(span.end))
            self._spans[span] = result
        return result
