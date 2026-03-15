from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from tcl_lsp.analysis.builtins import builtin_command
from tcl_lsp.analysis.facts.parsing import (
    ConditionVariableSubstitution,
    ListItem,
    is_simple_name,
    scan_static_tcl_substitutions,
    split_tcl_list,
)
from tcl_lsp.analysis.facts.utils import (
    body_span,
    command_documentation,
    extract_ifneeded_source_uri,
    extract_static_script,
    namespace_for_name,
    namespace_scope_id,
    normalize_command_name,
    proc_symbol_id,
    qualify_name,
    qualify_namespace,
    variable_symbol_id,
)
from tcl_lsp.analysis.model import (
    BindingKind,
    CommandCall,
    DocumentFacts,
    NamespaceScope,
    PackageIndexEntry,
    PackageProvide,
    PackageRequire,
    ParameterDecl,
    ProcDecl,
    VarBinding,
    VariableReference,
)
from tcl_lsp.common import Diagnostic, DocumentSymbol, Position, Span
from tcl_lsp.parser import Parser, collect_variable_substitutions, word_static_text
from tcl_lsp.parser.model import (
    BracedWord,
    Command,
    CommandSubstitution,
    ParseResult,
    Script,
    Word,
)


@dataclass(frozen=True, slots=True)
class _ExtractionContext:
    uri: str
    namespace: str
    scope_id: str
    procedure_symbol_id: str | None


@dataclass(frozen=True, slots=True)
class _SwitchLayout:
    branch_list_word: Word | None
    branch_words: tuple[Word, ...]
    regexp_binding_words: tuple[Word, ...]


@dataclass(frozen=True, slots=True)
class _SwitchOptionState:
    value_index: int
    regexp_binding_words: tuple[Word, ...]


class FactExtractor:
    def __init__(self, parser: Parser | None = None) -> None:
        self._parser = Parser() if parser is None else parser

    def extract(self, parse_result: ParseResult) -> DocumentFacts:
        collector = _FactCollector(parser=self._parser, parse_result=parse_result)
        return collector.collect()


class _FactCollector:
    def __init__(self, parser: Parser, parse_result: ParseResult) -> None:
        self._parser = parser
        self._parse_result = parse_result
        self._braced_token_text_by_span: dict[Span, str] = {}
        self._remember_braced_tokens(parse_result)
        self._diagnostics: list[Diagnostic] = list(parse_result.diagnostics)
        self._namespaces: list[NamespaceScope] = []
        self._procedures: list[ProcDecl] = []
        self._package_requires: list[PackageRequire] = []
        self._package_provides: list[PackageProvide] = []
        self._package_index_entries: list[PackageIndexEntry] = []
        self._variable_bindings: list[VarBinding] = []
        self._command_calls: list[CommandCall] = []
        self._variable_references: list[VariableReference] = []
        self._command_handlers: dict[str, Callable[[Command, _ExtractionContext], None]] = {
            'package': self._collect_package,
            'proc': self._collect_proc,
            'namespace': self._collect_namespace_eval,
            'set': self._collect_set,
            'foreach': self._collect_foreach,
            'if': self._collect_if,
            'switch': self._collect_switch,
            'catch': self._collect_catch,
        }

    def collect(self) -> DocumentFacts:
        root_context = self._namespace_context(self._parse_result.source_id, '::')
        self._collect_script(self._parse_result.script, root_context)
        return DocumentFacts(
            uri=self._parse_result.source_id,
            parse_result=self._parse_result,
            namespaces=tuple(self._namespaces),
            procedures=tuple(self._procedures),
            package_requires=tuple(self._package_requires),
            package_provides=tuple(self._package_provides),
            package_index_entries=tuple(self._package_index_entries),
            variable_bindings=tuple(self._variable_bindings),
            command_calls=tuple(self._command_calls),
            variable_references=tuple(self._variable_references),
            document_symbols=tuple(self._build_document_symbols()),
            diagnostics=tuple(self._diagnostics),
        )

    def _remember_braced_tokens(self, parse_result: ParseResult) -> None:
        for token in parse_result.tokens:
            if token.kind == 'braced_word':
                self._braced_token_text_by_span[token.span] = token.text

    def _collect_script(self, script: Script, context: _ExtractionContext) -> None:
        for command in script.commands:
            self._collect_command(command, context)

    def _collect_command(self, command: Command, context: _ExtractionContext) -> None:
        if not command.words:
            return

        command_name_word = command.words[0]
        command_name = word_static_text(command_name_word)
        self._record_command_call(
            command_name=command_name,
            command_span=command.span,
            name_span=command_name_word.span,
            context=context,
        )

        for word in command.words:
            self._collect_word_references(word, context)

        self._collect_builtin_subcommands(command, context)

        handler = self._command_handlers.get(command_name) if command_name is not None else None
        if handler is not None:
            handler(command, context)

    def _record_command_call(
        self,
        command_name: str | None,
        command_span: Span,
        name_span: Span,
        context: _ExtractionContext,
    ) -> None:
        self._command_calls.append(
            CommandCall(
                uri=context.uri,
                name=command_name,
                namespace=context.namespace,
                scope_id=context.scope_id,
                procedure_symbol_id=context.procedure_symbol_id,
                span=command_span,
                name_span=name_span,
                dynamic=command_name is None,
            )
        )

    def _collect_builtin_subcommands(self, command: Command, context: _ExtractionContext) -> None:
        static_prefix_parts: list[str] = []
        for index, word in enumerate(command.words):
            static_text = word_static_text(word)
            if static_text is None:
                return
            if index == 0:
                static_text = normalize_command_name(static_text)

            static_prefix_parts.append(static_text)
            if index == 0:
                continue

            builtin_name = ' '.join(static_prefix_parts)
            if builtin_command(builtin_name) is None:
                continue

            self._record_command_call(
                command_name=builtin_name,
                command_span=command.span,
                name_span=word.content_span,
                context=context,
            )

    def _collect_package(self, command: Command, context: _ExtractionContext) -> None:
        if len(command.words) < 2:
            return

        subcommand = word_static_text(command.words[1])
        if subcommand == 'require' and len(command.words) >= 3:
            package_name = word_static_text(command.words[2])
            if package_name is None:
                return
            version_constraints = tuple(
                version_text
                for word in command.words[3:]
                if (version_text := word_static_text(word)) is not None
            )
            self._package_requires.append(
                PackageRequire(
                    uri=context.uri,
                    name=package_name,
                    version_constraints=version_constraints,
                    span=command.words[2].span,
                )
            )
            return

        if subcommand == 'provide' and len(command.words) >= 3:
            package_name = word_static_text(command.words[2])
            if package_name is None:
                return
            version = word_static_text(command.words[3]) if len(command.words) >= 4 else None
            self._package_provides.append(
                PackageProvide(
                    uri=context.uri,
                    name=package_name,
                    version=version,
                    span=command.words[2].span,
                )
            )
            return

        if subcommand == 'ifneeded' and len(command.words) >= 4:
            package_name = word_static_text(command.words[2])
            if package_name is None:
                return
            version = word_static_text(command.words[3])
            source_uri = (
                extract_ifneeded_source_uri(command.words[4], context.uri)
                if len(command.words) >= 5
                else None
            )
            self._package_index_entries.append(
                PackageIndexEntry(
                    uri=context.uri,
                    name=package_name,
                    version=version,
                    source_uri=source_uri,
                    span=command.words[2].span,
                )
            )

    def _collect_word_references(self, word: Word, context: _ExtractionContext) -> None:
        for substitution in collect_variable_substitutions(word):
            self._record_variable_reference(
                name=substitution.name,
                span=substitution.span,
                context=context,
            )

        if isinstance(word, BracedWord):
            return

        for part in word.parts:
            if isinstance(part, CommandSubstitution):
                self._collect_script(part.script, context)

    def _collect_proc(self, command: Command, context: _ExtractionContext) -> None:
        proc_details = self._build_proc_declaration(command, context)
        if proc_details is None:
            return

        proc_decl, body_word = proc_details
        self._procedures.append(proc_decl)

        body_context = self._procedure_context(proc_decl)
        self._record_parameter_bindings(proc_decl.parameters, body_context)
        self._collect_embedded_body(body_word, body_context)

    def _collect_namespace_eval(self, command: Command, context: _ExtractionContext) -> None:
        namespace_eval = self._namespace_eval_details(command, context)
        if namespace_eval is None:
            return

        namespace_scope, body_word = namespace_eval
        self._namespaces.append(namespace_scope)

        if context.procedure_symbol_id is not None:
            return

        self._collect_embedded_body(
            body_word,
            self._namespace_context(context.uri, namespace_scope.qualified_name),
        )

    def _collect_set(self, command: Command, context: _ExtractionContext) -> None:
        if len(command.words) < 2:
            return
        variable_name = self._simple_variable_name(command.words[1])
        if variable_name is None:
            return

        if len(command.words) >= 3:
            self._record_variable_binding(
                name=variable_name,
                span=command.words[1].span,
                context=context,
                kind='set',
            )
            return

        self._record_variable_reference(
            name=variable_name,
            span=command.words[1].span,
            context=context,
        )

    def _collect_foreach(self, command: Command, context: _ExtractionContext) -> None:
        if len(command.words) < 4:
            return
        variables = self._parse_list_items(command.words[1])
        for item in variables:
            if not is_simple_name(item.text):
                continue
            self._record_variable_binding(
                name=item.text,
                span=item.span,
                context=context,
                kind='foreach',
            )

        self._collect_embedded_body(command.words[3], context)

    def _collect_if(self, command: Command, context: _ExtractionContext) -> None:
        if len(command.words) < 3:
            return

        index = self._collect_if_clause(command.words, 1, context)
        while index is not None and index < len(command.words):
            keyword = word_static_text(command.words[index])
            if keyword == 'elseif':
                index = self._collect_if_clause(command.words, index + 1, context)
                continue

            if keyword == 'else':
                self._collect_if_else_clause(command.words, index, context)
            return

    def _collect_catch(self, command: Command, context: _ExtractionContext) -> None:
        if len(command.words) < 2:
            return

        self._collect_embedded_body(command.words[1], context)

        for variable_word in command.words[2:4]:
            self._record_simple_binding_word(variable_word, context, kind='catch')

    def _collect_switch(self, command: Command, context: _ExtractionContext) -> None:
        layout = self._switch_layout(command)
        if layout is None:
            return

        self._collect_switch_regexp_bindings(layout.regexp_binding_words, context)

        if layout.branch_list_word is not None:
            self._collect_switch_branch_list(layout.branch_list_word, context)
            return

        branch_body_words = self._switch_branch_body_words(layout.branch_words)
        if branch_body_words is None:
            return

        for body_word in branch_body_words:
            self._collect_embedded_body(body_word, context)

    def _switch_layout(self, command: Command) -> _SwitchLayout | None:
        if len(command.words) < 3:
            return None

        option_state = self._scan_switch_options(command.words)
        if option_state is None or option_state.value_index >= len(command.words):
            return None

        branch_words = tuple(command.words[option_state.value_index + 1 :])
        if not branch_words:
            return None

        if len(branch_words) == 1:
            return _SwitchLayout(
                branch_list_word=branch_words[0],
                branch_words=(),
                regexp_binding_words=option_state.regexp_binding_words,
            )

        return _SwitchLayout(
            branch_list_word=None,
            branch_words=branch_words,
            regexp_binding_words=option_state.regexp_binding_words,
        )

    def _collect_switch_branch_list(self, word: Word, context: _ExtractionContext) -> None:
        items = self._parse_list_items(word)
        if len(items) % 2 != 0:
            return

        for index in range(1, len(items), 2):
            body_item = items[index]
            if body_item.text == '-':
                continue
            self._collect_embedded_script_text(body_item.text, body_item.content_start, context)

    def _collect_embedded_body(self, word: Word, context: _ExtractionContext) -> None:
        embedded_body = extract_static_script(word)
        if embedded_body is None:
            return

        self._collect_embedded_script_text(embedded_body[0], embedded_body[1], context)

    def _collect_embedded_script_text(
        self,
        text: str,
        start_position: Position,
        context: _ExtractionContext,
    ) -> None:
        body_result = self._parse_embedded_script(text, start_position, source_id=context.uri)
        self._collect_script(body_result.script, context)

    def _collect_if_condition(self, word: Word, context: _ExtractionContext) -> None:
        if not isinstance(word, BracedWord):
            return

        source_text = self._braced_token_text_by_span.get(word.span)
        if source_text is None:
            return

        condition_text = source_text[1:]
        if condition_text.endswith('}'):
            condition_text = condition_text[:-1]

        for substitution in scan_static_tcl_substitutions(condition_text, word.content_span.start):
            if isinstance(substitution, ConditionVariableSubstitution):
                self._record_variable_reference(
                    name=substitution.name,
                    span=substitution.span,
                    context=context,
                )
                continue

            nested_result = self._parse_embedded_script(
                substitution.text,
                substitution.content_span.start,
                source_id=context.uri,
            )
            self._collect_script(nested_result.script, context)

    def _namespace_context(self, uri: str, namespace: str) -> _ExtractionContext:
        return _ExtractionContext(
            uri=uri,
            namespace=namespace,
            scope_id=namespace_scope_id(namespace),
            procedure_symbol_id=None,
        )

    def _procedure_context(self, proc_decl: ProcDecl) -> _ExtractionContext:
        return _ExtractionContext(
            uri=proc_decl.uri,
            namespace=proc_decl.namespace,
            scope_id=proc_decl.symbol_id,
            procedure_symbol_id=proc_decl.symbol_id,
        )

    def _parse_embedded_script(
        self,
        text: str,
        start_position: Position,
        *,
        source_id: str,
    ) -> ParseResult:
        parse_result = self._parser.parse_embedded_script(
            source_id=source_id,
            text=text,
            start_position=start_position,
        )
        self._remember_braced_tokens(parse_result)
        self._diagnostics.extend(parse_result.diagnostics)
        return parse_result

    def _record_variable_reference(
        self,
        name: str,
        span: Span,
        context: _ExtractionContext,
    ) -> None:
        self._variable_references.append(
            VariableReference(
                uri=context.uri,
                name=name,
                namespace=context.namespace,
                scope_id=context.scope_id,
                procedure_symbol_id=context.procedure_symbol_id,
                span=span,
            )
        )

    def _record_variable_binding(
        self,
        name: str,
        span: Span,
        context: _ExtractionContext,
        kind: BindingKind,
    ) -> None:
        self._variable_bindings.append(
            VarBinding(
                symbol_id=variable_symbol_id(context.uri, context.scope_id, name),
                uri=context.uri,
                name=name,
                scope_id=context.scope_id,
                namespace=context.namespace,
                procedure_symbol_id=context.procedure_symbol_id,
                kind=kind,
                span=span,
            )
        )

    def _simple_variable_name(self, word: Word) -> str | None:
        variable_name = word_static_text(word)
        if variable_name is None or not is_simple_name(variable_name):
            return None
        return variable_name

    def _record_simple_binding_word(
        self,
        word: Word,
        context: _ExtractionContext,
        kind: BindingKind,
    ) -> None:
        variable_name = self._simple_variable_name(word)
        if variable_name is None:
            return
        self._record_variable_binding(
            name=variable_name,
            span=word.span,
            context=context,
            kind=kind,
        )

    def _build_proc_declaration(
        self,
        command: Command,
        context: _ExtractionContext,
    ) -> tuple[ProcDecl, Word] | None:
        if len(command.words) < 4:
            return None

        name_word = command.words[1]
        args_word = command.words[2]
        body_word = command.words[3]
        raw_name = word_static_text(name_word)
        if raw_name is None:
            return None

        qualified_name = qualify_name(raw_name, context.namespace)
        proc_id = proc_symbol_id(context.uri, qualified_name, name_word.span.start.offset)
        parameters = self._parse_proc_parameters(
            args_word,
            uri=context.uri,
            proc_symbol_id=proc_id,
        )
        proc_namespace = namespace_for_name(qualified_name)
        return (
            ProcDecl(
                symbol_id=proc_id,
                uri=context.uri,
                name=raw_name,
                qualified_name=qualified_name,
                namespace=proc_namespace,
                span=command.span,
                name_span=name_word.span,
                parameters=parameters,
                documentation=command_documentation(command),
                body_span=body_span(body_word),
            ),
            body_word,
        )

    def _parse_proc_parameters(
        self,
        word: Word,
        *,
        uri: str,
        proc_symbol_id: str,
    ) -> tuple[ParameterDecl, ...]:
        parameters: list[ParameterDecl] = []
        for item in self._parse_parameter_items(word):
            parameter_name, parameter_span = self._parameter_from_item(item)
            if parameter_name is None:
                continue
            parameters.append(
                ParameterDecl(
                    symbol_id=variable_symbol_id(uri, proc_symbol_id, parameter_name),
                    name=parameter_name,
                    span=parameter_span,
                )
            )
        return tuple(parameters)

    def _record_parameter_bindings(
        self,
        parameters: tuple[ParameterDecl, ...],
        context: _ExtractionContext,
    ) -> None:
        for parameter in parameters:
            self._record_variable_binding(
                name=parameter.name,
                span=parameter.span,
                context=context,
                kind='parameter',
            )

    def _namespace_eval_details(
        self,
        command: Command,
        context: _ExtractionContext,
    ) -> tuple[NamespaceScope, Word] | None:
        if len(command.words) < 4:
            return None
        if word_static_text(command.words[1]) != 'eval':
            return None

        namespace_word = command.words[2]
        namespace_name = word_static_text(namespace_word)
        if namespace_name is None:
            return None

        qualified_namespace = qualify_namespace(namespace_name, context.namespace)
        return (
            NamespaceScope(
                uri=context.uri,
                name=namespace_name,
                qualified_name=qualified_namespace,
                span=namespace_word.span,
                selection_span=namespace_word.span,
            ),
            command.words[3],
        )

    def _collect_if_clause(
        self,
        words: tuple[Word, ...],
        condition_index: int,
        context: _ExtractionContext,
    ) -> int | None:
        if condition_index >= len(words):
            return None

        self._collect_if_condition(words[condition_index], context)
        body_index = self._if_body_index(words, condition_index + 1)
        if body_index is None:
            return None

        self._collect_embedded_body(words[body_index], context)
        return body_index + 1

    def _if_body_index(self, words: tuple[Word, ...], index: int) -> int | None:
        if index < len(words) and word_static_text(words[index]) == 'then':
            index += 1
        if index >= len(words):
            return None
        return index

    def _collect_if_else_clause(
        self,
        words: tuple[Word, ...],
        keyword_index: int,
        context: _ExtractionContext,
    ) -> None:
        body_index = keyword_index + 1
        if body_index >= len(words):
            return
        self._collect_embedded_body(words[body_index], context)

    def _collect_switch_regexp_bindings(
        self,
        binding_words: tuple[Word, ...],
        context: _ExtractionContext,
    ) -> None:
        for binding_word in binding_words:
            self._record_simple_binding_word(binding_word, context, kind='switch')

    def _switch_branch_body_words(self, branch_words: tuple[Word, ...]) -> tuple[Word, ...] | None:
        if len(branch_words) % 2 != 0:
            return None

        body_words: list[Word] = []
        for index in range(1, len(branch_words), 2):
            body_word = branch_words[index]
            if word_static_text(body_word) == '-':
                continue
            body_words.append(body_word)
        return tuple(body_words)

    def _scan_switch_options(self, words: tuple[Word, ...]) -> _SwitchOptionState | None:
        index = 1
        regexp_binding_words: list[Word] = []
        regexp_mode = False

        while index < len(words):
            option = word_static_text(words[index])
            if option == '--':
                index += 1
                break
            if option in {'-exact', '-glob', '-nocase'}:
                index += 1
                continue
            if option == '-regexp':
                regexp_mode = True
                index += 1
                continue
            if option in {'-matchvar', '-indexvar'}:
                if index + 1 >= len(words):
                    return None
                if regexp_mode:
                    regexp_binding_words.append(words[index + 1])
                index += 2
                continue
            break

        return _SwitchOptionState(
            value_index=index,
            regexp_binding_words=tuple(regexp_binding_words),
        )

    def _parse_parameter_items(self, word: Word) -> tuple[ListItem, ...]:
        return tuple(self._parse_list_items(word))

    def _parse_list_items(self, word: Word) -> list[ListItem]:
        static_text = word_static_text(word)
        if static_text is None:
            return []
        return split_tcl_list(static_text, word.content_span.start)

    def _parameter_from_item(self, item: ListItem) -> tuple[str | None, Span]:
        if ' ' not in item.text and '\t' not in item.text and '\n' not in item.text:
            return item.text, item.span

        subitems = split_tcl_list(item.text, item.content_start)
        if not subitems:
            return None, item.span
        return subitems[0].text, subitems[0].span

    def _build_document_symbols(self) -> list[DocumentSymbol]:
        symbols: list[DocumentSymbol] = []
        for namespace in sorted(self._namespaces, key=lambda item: item.span.start.offset):
            symbols.append(
                DocumentSymbol(
                    name=namespace.qualified_name,
                    kind='namespace',
                    span=namespace.span,
                    selection_span=namespace.selection_span,
                    children=(),
                )
            )
        for proc in sorted(self._procedures, key=lambda item: item.name_span.start.offset):
            symbols.append(
                DocumentSymbol(
                    name=proc.qualified_name,
                    kind='function',
                    span=proc.span,
                    selection_span=proc.name_span,
                    children=(),
                )
            )
        return symbols
