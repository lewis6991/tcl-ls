from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from tcl_lsp.analysis.model import AnalysisResult, DocumentFacts, ResolutionResult, VarBinding
from tcl_lsp.common import Span

type SemanticTokenType = Literal[
    'comment',
    'keyword',
    'namespace',
    'function',
    'parameter',
    'variable',
    'string',
    'operator',
]
type SemanticTokenModifier = Literal['declaration', 'defaultLibrary']

SEMANTIC_TOKEN_TYPES: tuple[SemanticTokenType, ...] = (
    'comment',
    'keyword',
    'namespace',
    'function',
    'parameter',
    'variable',
    'string',
    'operator',
)
SEMANTIC_TOKEN_MODIFIERS: tuple[SemanticTokenModifier, ...] = ('declaration', 'defaultLibrary')
_TOKEN_TYPE_INDICES = {token_type: index for index, token_type in enumerate(SEMANTIC_TOKEN_TYPES)}
_TOKEN_MODIFIER_BITS = {
    modifier: 1 << index for index, modifier in enumerate(SEMANTIC_TOKEN_MODIFIERS)
}
_TOKEN_PRIORITY = {
    'comment': 0,
    'namespace': 1,
    'function': 2,
    'keyword': 3,
    'variable': 4,
    'parameter': 5,
    'string': 6,
    'operator': 7,
}
_KEYWORD_COMMANDS = frozenset(
    {
        'catch',
        'for',
        'foreach',
        'global',
        'if',
        'lmap',
        'namespace',
        'namespace eval',
        'package',
        'package ifneeded',
        'package provide',
        'package require',
        'proc',
        'return',
        'set',
        'source',
        'switch',
        'upvar',
        'variable',
        'vwait',
        'while',
    }
)
_KEYWORD_ARGUMENTS_BY_COMMAND: dict[str, frozenset[str]] = {
    'if': frozenset({'else', 'elseif', 'then'}),
}


@dataclass(frozen=True, slots=True)
class _SemanticToken:
    span: Span
    token_type: SemanticTokenType
    modifier_bits: int = 0


def encode_document_semantic_tokens(
    *,
    text: str,
    facts: DocumentFacts,
    analysis: AnalysisResult,
) -> tuple[int, ...]:
    tokens = _collect_semantic_tokens(text=text, facts=facts, analysis=analysis)
    encoded: list[int] = []
    previous_line = 0
    previous_character = 0
    first_token = True

    for token in tokens:
        for token_span in _split_multiline_span(text, token.span):
            line = token_span.start.line
            character = token_span.start.character
            length = token_span.end.character - token_span.start.character
            if length <= 0:
                continue

            if first_token:
                delta_line = line
                delta_character = character
                first_token = False
            else:
                delta_line = line - previous_line
                delta_character = character if delta_line else character - previous_character

            encoded.extend(
                (
                    delta_line,
                    delta_character,
                    length,
                    _TOKEN_TYPE_INDICES[token.token_type],
                    token.modifier_bits,
                )
            )
            previous_line = line
            previous_character = character

    return tuple(encoded)


def _collect_semantic_tokens(
    *,
    text: str,
    facts: DocumentFacts,
    analysis: AnalysisResult,
) -> tuple[_SemanticToken, ...]:
    tokens_by_span: dict[tuple[int, int], _SemanticToken] = {}
    parameter_symbol_ids = {
        parameter.symbol_id for procedure in facts.procedures for parameter in procedure.parameters
    }
    resolution_by_key = {
        _resolution_key(resolution): resolution for resolution in analysis.resolutions
    }
    declaration_spans = _declaration_spans(facts.variable_bindings)

    for comment_span in facts.comment_spans:
        _add_token(tokens_by_span, _SemanticToken(span=comment_span, token_type='comment'))

    for string_span in facts.string_spans:
        _add_token(tokens_by_span, _SemanticToken(span=string_span, token_type='string'))

    for operator_span in facts.operator_spans:
        _add_token(tokens_by_span, _SemanticToken(span=operator_span, token_type='operator'))

    for namespace in facts.namespaces:
        _add_token(
            tokens_by_span,
            _SemanticToken(
                span=namespace.selection_span,
                token_type='namespace',
                modifier_bits=_modifier_bits('declaration'),
            ),
        )

    for procedure in facts.procedures:
        _add_token(
            tokens_by_span,
            _SemanticToken(
                span=procedure.name_span,
                token_type='function',
                modifier_bits=_modifier_bits('declaration'),
            ),
        )
        for parameter in procedure.parameters:
            parameter_span = _span_for_name(text, parameter.span, parameter.name)
            _add_token(
                tokens_by_span,
                _SemanticToken(
                    span=parameter_span,
                    token_type='parameter',
                    modifier_bits=_modifier_bits('declaration'),
                ),
            )

    for command_call in facts.command_calls:
        resolution = resolution_by_key.get(('command', command_call.name_span))
        token_type = 'function'
        modifier_bits = 0
        normalized_name = _normalized_command_name(command_call.name)
        if (
            resolution is not None
            and resolution.target_symbol_ids
            and all(symbol_id.startswith('builtin::') for symbol_id in resolution.target_symbol_ids)
        ):
            if normalized_name in _KEYWORD_COMMANDS:
                token_type = 'keyword'
            else:
                modifier_bits |= _modifier_bits('defaultLibrary')
        _add_token(
            tokens_by_span,
            _SemanticToken(
                span=command_call.name_span,
                token_type=token_type,
                modifier_bits=modifier_bits,
            ),
        )
        if normalized_name is None:
            continue
        keyword_arguments = _KEYWORD_ARGUMENTS_BY_COMMAND.get(normalized_name)
        if keyword_arguments is None:
            continue
        for argument_text, argument_span in zip(
            command_call.arg_texts, command_call.arg_spans, strict=True
        ):
            if argument_text not in keyword_arguments:
                continue
            _add_token(
                tokens_by_span,
                _SemanticToken(
                    span=_span_for_name(text, argument_span, argument_text),
                    token_type='keyword',
                ),
            )

    for binding in facts.variable_bindings:
        token_type = _variable_token_type(
            symbol_ids=(binding.symbol_id,),
            parameter_symbol_ids=parameter_symbol_ids,
        )
        modifier_bits = 0
        if _span_key(binding.span) in declaration_spans:
            modifier_bits |= _modifier_bits('declaration')
        binding_span = _span_for_name(text, binding.span, binding.name)
        _add_token(
            tokens_by_span,
            _SemanticToken(
                span=binding_span,
                token_type=token_type,
                modifier_bits=modifier_bits,
            ),
        )

    for reference in facts.variable_references:
        resolution = resolution_by_key.get(('variable', reference.span))
        symbol_ids = resolution.target_symbol_ids if resolution is not None else ()
        reference_span = _span_for_name(text, reference.span, reference.name)
        _add_token(
            tokens_by_span,
            _SemanticToken(
                span=reference_span,
                token_type=_variable_token_type(
                    symbol_ids=symbol_ids,
                    parameter_symbol_ids=parameter_symbol_ids,
                ),
            ),
        )

    return tuple(
        token
        for _, token in sorted(
            tokens_by_span.items(),
            key=lambda item: (
                item[1].span.start.line,
                item[1].span.start.character,
                item[1].span.end.line,
                item[1].span.end.character,
                _TOKEN_TYPE_INDICES[item[1].token_type],
                item[1].modifier_bits,
            ),
        )
    )


def _declaration_spans(bindings: tuple[VarBinding, ...]) -> set[tuple[int, int]]:
    declaration_spans: set[tuple[int, int]] = set()
    seen_symbols: set[str] = set()
    for binding in sorted(bindings, key=lambda item: item.span.start.offset):
        if binding.symbol_id in seen_symbols:
            continue
        seen_symbols.add(binding.symbol_id)
        declaration_spans.add(_span_key(binding.span))
    return declaration_spans


def _resolution_key(resolution: ResolutionResult) -> tuple[str, Span]:
    return resolution.reference.kind, resolution.reference.span


def _variable_token_type(
    *,
    symbol_ids: tuple[str, ...],
    parameter_symbol_ids: set[str],
) -> SemanticTokenType:
    if symbol_ids and all(symbol_id in parameter_symbol_ids for symbol_id in symbol_ids):
        return 'parameter'
    return 'variable'


def _modifier_bits(*modifiers: SemanticTokenModifier) -> int:
    return sum(_TOKEN_MODIFIER_BITS[modifier] for modifier in modifiers)


def _normalized_command_name(name: str | None) -> str | None:
    if name is None:
        return None
    return name[2:] if name.startswith('::') else name


def _span_for_name(text: str, span: Span, name: str) -> Span:
    if not name:
        return span

    raw_text = text[span.start.offset : span.end.offset]
    name_index = raw_text.find(name)
    if name_index < 0:
        return span

    token_start = span.start.advance(raw_text[:name_index])
    return Span(start=token_start, end=token_start.advance(name))


def _span_key(span: Span) -> tuple[int, int]:
    return span.start.offset, span.end.offset


def _add_token(
    tokens_by_span: dict[tuple[int, int], _SemanticToken],
    token: _SemanticToken,
) -> None:
    token_key = _span_key(token.span)
    existing = tokens_by_span.get(token_key)
    if existing is None:
        tokens_by_span[token_key] = token
        return

    if existing.token_type == token.token_type:
        tokens_by_span[token_key] = _SemanticToken(
            span=existing.span,
            token_type=existing.token_type,
            modifier_bits=existing.modifier_bits | token.modifier_bits,
        )
        return

    if _TOKEN_PRIORITY[token.token_type] > _TOKEN_PRIORITY[existing.token_type]:
        tokens_by_span[token_key] = token


def _split_multiline_span(text: str, span: Span) -> tuple[Span, ...]:
    fragment = text[span.start.offset : span.end.offset]
    if '\n' not in fragment:
        return (span,)

    spans: list[Span] = []
    line_start = span.start
    remainder = fragment
    while remainder:
        newline_index = remainder.find('\n')
        if newline_index < 0:
            if remainder:
                spans.append(Span(start=line_start, end=line_start.advance(remainder)))
            break

        line_fragment = remainder[:newline_index]
        if line_fragment:
            spans.append(Span(start=line_start, end=line_start.advance(line_fragment)))
        line_start = line_start.advance(remainder[: newline_index + 1])
        remainder = remainder[newline_index + 1 :]

    return tuple(spans)
