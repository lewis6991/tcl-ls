from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from tcl_lsp.analysis.builtins import builtin_command
from tcl_lsp.analysis.facts.lowering import (
    LoweredCatchCommand,
    LoweredCommand,
    LoweredCondition,
    LoweredForCommand,
    LoweredForeachCommand,
    LoweredIfCommand,
    LoweredLmapCommand,
    LoweredNamespaceEvalCommand,
    LoweredProcCommand,
    LoweredScript,
    LoweredScriptBody,
    LoweredSwitchCommand,
    LoweredWhileCommand,
    LoweredWordReferences,
    lower_parse_result,
)
from tcl_lsp.analysis.facts.parsing import ListItem, is_simple_name, split_tcl_list
from tcl_lsp.analysis.facts.utils import (
    extract_ifneeded_source_uri,
    extract_static_source_uri,
    name_tail,
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
    CommandImport,
    DocumentFacts,
    NamespaceScope,
    PackageIndexEntry,
    PackageProvide,
    PackageRequire,
    ParameterDecl,
    ProcDecl,
    SourceDirective,
    VarBinding,
    VariableReference,
)
from tcl_lsp.common import Diagnostic, DocumentSymbol, Span
from tcl_lsp.parser import Parser, word_static_text
from tcl_lsp.parser.model import (
    BracedWord,
    Command,
    CommandSubstitution,
    ParseResult,
    VariableSubstitution,
    Word,
)


@dataclass(frozen=True, slots=True)
class _ExtractionContext:
    uri: str
    namespace: str
    scope_id: str
    procedure_symbol_id: str | None


@dataclass(frozen=True, slots=True)
class _VariableTarget:
    name: str
    namespace: str
    scope_id: str
    symbol_id: str


class FactExtractor:
    __slots__ = ('_parser',)

    def __init__(self, parser: Parser | None = None) -> None:
        self._parser = Parser() if parser is None else parser

    def extract(self, parse_result: ParseResult, *, include_parse_result: bool = True) -> DocumentFacts:
        lowering_result = lower_parse_result(parse_result, parser=self._parser)
        collector = _FactCollector(
            parser=self._parser,
            parse_result=parse_result,
            lowered_script=lowering_result.script,
            diagnostics=parse_result.diagnostics + lowering_result.diagnostics,
            include_parse_result=include_parse_result,
        )
        return collector.collect()


class _FactCollector:
    __slots__ = (
        '_command_calls',
        '_command_handlers',
        '_command_imports',
        '_diagnostics',
        '_include_parse_result',
        '_linked_variables_by_scope',
        '_lowered_script',
        '_namespaces',
        '_package_index_entries',
        '_package_provides',
        '_package_requires',
        '_parse_result',
        '_parser',
        '_procedures',
        '_source_directives',
        '_variable_bindings',
        '_variable_references',
    )

    def __init__(
        self,
        parser: Parser,
        parse_result: ParseResult,
        *,
        lowered_script: LoweredScript,
        diagnostics: tuple[Diagnostic, ...],
        include_parse_result: bool,
    ) -> None:
        self._parser = parser
        self._parse_result = parse_result
        self._lowered_script = lowered_script
        self._include_parse_result = include_parse_result
        self._diagnostics: list[Diagnostic] = list(diagnostics)
        self._namespaces: list[NamespaceScope] = []
        self._procedures: list[ProcDecl] = []
        self._source_directives: list[SourceDirective] = []
        self._command_imports: list[CommandImport] = []
        self._package_requires: list[PackageRequire] = []
        self._package_provides: list[PackageProvide] = []
        self._package_index_entries: list[PackageIndexEntry] = []
        self._variable_bindings: list[VarBinding] = []
        self._command_calls: list[CommandCall] = []
        self._variable_references: list[VariableReference] = []
        self._linked_variables_by_scope: dict[str, dict[str, _VariableTarget]] = {}
        self._command_handlers: dict[str, Callable[[Command, _ExtractionContext], None]] = {
            'append': self._collect_append,
            'array': self._collect_array,
            'binary': self._collect_binary,
            'package': self._collect_package,
            'namespace': self._collect_namespace,
            'set': self._collect_set,
            'global': self._collect_global,
            'gets': self._collect_gets,
            'info': self._collect_info,
            'incr': self._collect_incr,
            'lappend': self._collect_lappend,
            'lassign': self._collect_lassign,
            'regexp': self._collect_regexp,
            'regsub': self._collect_regsub,
            'scan': self._collect_scan,
            'source': self._collect_source,
            'upvar': self._collect_upvar,
            'variable': self._collect_variable,
            'vwait': self._collect_vwait,
        }

    def collect(self) -> DocumentFacts:
        root_context = self._namespace_context(self._parse_result.source_id, '::')
        self._collect_lowered_script(self._lowered_script, root_context)
        return DocumentFacts(
            uri=self._parse_result.source_id,
            parse_result=self._parse_result if self._include_parse_result else None,
            namespaces=tuple(self._namespaces),
            procedures=tuple(self._procedures),
            source_directives=tuple(self._source_directives),
            command_imports=tuple(self._command_imports),
            package_requires=tuple(self._package_requires),
            package_provides=tuple(self._package_provides),
            package_index_entries=tuple(self._package_index_entries),
            variable_bindings=tuple(self._variable_bindings),
            command_calls=tuple(self._command_calls),
            variable_references=tuple(self._variable_references),
            document_symbols=tuple(self._build_document_symbols()),
            diagnostics=tuple(self._diagnostics),
        )

    def _collect_lowered_script(self, script: LoweredScript, context: _ExtractionContext) -> None:
        for command in script.commands:
            self._collect_lowered_command(command, context)

    def _collect_lowered_command(self, command: LoweredCommand, context: _ExtractionContext) -> None:
        syntax_command = command.command
        command_name = self._collect_command_common(command, context)
        normalized_command_name = (
            normalize_command_name(command_name) if command_name is not None else None
        )
        if isinstance(command, LoweredProcCommand):
            self._collect_lowered_proc(command, context)
            return
        if isinstance(command, LoweredNamespaceEvalCommand):
            self._collect_lowered_namespace_eval(command, context)
            return
        if isinstance(command, LoweredForeachCommand):
            self._collect_lowered_foreach(command, context)
            return
        if isinstance(command, LoweredLmapCommand):
            self._collect_lowered_lmap(command, context)
            return
        if isinstance(command, LoweredForCommand):
            self._collect_lowered_for(command, context)
            return
        if isinstance(command, LoweredIfCommand):
            self._collect_lowered_if(command, context)
            return
        if isinstance(command, LoweredCatchCommand):
            self._collect_lowered_catch(command, context)
            return
        if isinstance(command, LoweredSwitchCommand):
            self._collect_lowered_switch(command, context)
            return
        if isinstance(command, LoweredWhileCommand):
            self._collect_lowered_while(command, context)
            return

        handler = (
            self._command_handlers.get(normalized_command_name)
            if normalized_command_name is not None
            else None
        )
        if handler is not None:
            handler(syntax_command, context)

    def _collect_command_common(
        self,
        command: LoweredCommand,
        context: _ExtractionContext,
    ) -> str | None:
        syntax_command = command.command
        if not syntax_command.words:
            return None

        command_name_word = syntax_command.words[0]
        self._record_command_call(
            command_name=command.command_name,
            command_span=syntax_command.span,
            name_span=command_name_word.span,
            arg_texts=tuple(word_static_text(word) for word in syntax_command.words[1:]),
            context=context,
        )

        for word_references in command.word_references:
            self._collect_lowered_word_references(word_references, context)

        self._collect_builtin_subcommands(syntax_command, context)
        return command.command_name

    def _record_command_call(
        self,
        command_name: str | None,
        command_span: Span,
        name_span: Span,
        arg_texts: tuple[str | None, ...],
        context: _ExtractionContext,
    ) -> None:
        self._command_calls.append(
            CommandCall(
                uri=context.uri,
                name=command_name,
                arg_texts=arg_texts,
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
                arg_texts=tuple(word_static_text(argument) for argument in command.words[index + 1 :]),
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

    def _collect_source(self, command: Command, context: _ExtractionContext) -> None:
        target_uri = extract_static_source_uri(command, context.uri)
        if target_uri is None:
            return

        self._source_directives.append(
            SourceDirective(
                uri=context.uri,
                target_uri=target_uri,
                span=command.span,
            )
        )

    def _collect_lowered_word_references(
        self,
        word_references: LoweredWordReferences,
        context: _ExtractionContext,
    ) -> None:
        for substitution in word_references.variable_substitutions:
            self._record_variable_reference(
                name=substitution.name,
                span=substitution.span,
                context=context,
            )

        for script in word_references.command_substitutions:
            self._collect_lowered_script(script, context)

    def _collect_lowered_proc(
        self,
        command: LoweredProcCommand,
        context: _ExtractionContext,
    ) -> None:
        if command.name is None or command.name_span is None or command.body_span is None:
            return

        qualified_name = qualify_name(command.name, context.namespace)
        proc_id = proc_symbol_id(context.uri, qualified_name, command.name_span.start.offset)
        proc_decl = ProcDecl(
            symbol_id=proc_id,
            uri=context.uri,
            name=command.name,
            qualified_name=qualified_name,
            namespace=namespace_for_name(qualified_name),
            span=command.command.span,
            name_span=command.name_span,
            parameters=self._parameter_decls_from_items(
                command.parameter_items,
                uri=context.uri,
                proc_symbol_id=proc_id,
            ),
            documentation=command.documentation,
            body_span=command.body_span,
        )
        self._procedures.append(proc_decl)

        body_context = self._procedure_context(proc_decl)
        self._record_parameter_bindings(proc_decl.parameters, body_context)
        self._collect_lowered_body(command.body, body_context)

    def _collect_namespace(self, command: Command, context: _ExtractionContext) -> None:
        if len(command.words) < 2:
            return

        if word_static_text(command.words[1]) == 'import':
            self._collect_namespace_import(command, context)

    def _collect_lowered_namespace_eval(
        self,
        command: LoweredNamespaceEvalCommand,
        context: _ExtractionContext,
    ) -> None:
        if command.namespace_name is None or command.namespace_span is None:
            return

        namespace_scope = NamespaceScope(
            uri=context.uri,
            name=command.namespace_name,
            qualified_name=qualify_namespace(command.namespace_name, context.namespace),
            span=command.namespace_span,
            selection_span=command.namespace_span,
        )
        self._namespaces.append(namespace_scope)

        if context.procedure_symbol_id is not None:
            return

        self._collect_lowered_body(
            command.body,
            self._namespace_context(context.uri, namespace_scope.qualified_name),
        )

    def _collect_namespace_import(self, command: Command, context: _ExtractionContext) -> None:
        for pattern_word in command.words[2:]:
            pattern = word_static_text(pattern_word)
            if pattern is None:
                continue

            exact_import = self._exact_command_import(pattern, context.namespace)
            if exact_import is not None:
                imported_name, target_name = exact_import
                self._command_imports.append(
                    CommandImport(
                        uri=context.uri,
                        namespace=context.namespace,
                        kind='exact',
                        imported_name=imported_name,
                        target_name=target_name,
                        span=pattern_word.span,
                    )
                )
                continue

            target_namespace = self._wildcard_import_namespace(pattern, context.namespace)
            if target_namespace is None:
                continue

            self._command_imports.append(
                CommandImport(
                    uri=context.uri,
                    namespace=context.namespace,
                    kind='namespace-wildcard',
                    imported_name=None,
                    target_name=target_namespace,
                    span=pattern_word.span,
                )
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
            if context.procedure_symbol_id is None:
                self._record_variable_reference(
                    name=variable_name,
                    span=command.words[1].span,
                    context=context,
                )
            return

        self._record_variable_reference(
            name=variable_name,
            span=command.words[1].span,
            context=context,
        )

    def _collect_array(self, command: Command, context: _ExtractionContext) -> None:
        if len(command.words) < 3:
            return

        subcommand = word_static_text(command.words[1])
        if subcommand == 'set':
            self._record_simple_binding_word(command.words[2], context, kind='array')
            if context.procedure_symbol_id is None:
                self._record_simple_reference_word(command.words[2], context)
            return

        if subcommand in {'exists', 'get', 'names', 'size', 'startsearch', 'statistics', 'unset'}:
            self._record_simple_reference_word(command.words[2], context)

    def _collect_append(self, command: Command, context: _ExtractionContext) -> None:
        self._record_variable_writer(command, context, kind='append')

    def _collect_incr(self, command: Command, context: _ExtractionContext) -> None:
        self._record_variable_writer(command, context, kind='incr')

    def _collect_lappend(self, command: Command, context: _ExtractionContext) -> None:
        self._record_variable_writer(command, context, kind='lappend')

    def _collect_gets(self, command: Command, context: _ExtractionContext) -> None:
        if len(command.words) < 3:
            return
        self._record_simple_binding_word(command.words[2], context, kind='gets')

    def _collect_lassign(self, command: Command, context: _ExtractionContext) -> None:
        if len(command.words) < 3:
            return
        for variable_word in command.words[2:]:
            self._record_simple_binding_word(variable_word, context, kind='lassign')

    def _collect_scan(self, command: Command, context: _ExtractionContext) -> None:
        if len(command.words) < 4:
            return
        for variable_word in command.words[3:]:
            self._record_simple_binding_word(variable_word, context, kind='scan')

    def _collect_binary(self, command: Command, context: _ExtractionContext) -> None:
        if len(command.words) < 5:
            return
        if word_static_text(command.words[1]) != 'scan':
            return
        for variable_word in command.words[4:]:
            self._record_simple_binding_word(variable_word, context, kind='scan')

    def _collect_regexp(self, command: Command, context: _ExtractionContext) -> None:
        value_start = self._regex_value_start_index(command)
        if value_start is None or len(command.words) < value_start + 3:
            return
        for variable_word in command.words[value_start + 2 :]:
            self._record_simple_binding_word(variable_word, context, kind='regexp')

    def _collect_regsub(self, command: Command, context: _ExtractionContext) -> None:
        value_start = self._regex_value_start_index(command)
        if value_start is None or len(command.words) <= value_start + 3:
            return
        self._record_simple_binding_word(command.words[value_start + 3], context, kind='regsub')

    def _collect_lowered_foreach(
        self,
        command: LoweredForeachCommand,
        context: _ExtractionContext,
    ) -> None:
        self._record_list_item_bindings(command.variable_items, context=context, kind='foreach')
        self._collect_lowered_body(command.body, context)

    def _collect_lowered_lmap(
        self,
        command: LoweredLmapCommand,
        context: _ExtractionContext,
    ) -> None:
        self._record_list_item_bindings(command.variable_items, context=context, kind='lmap')
        self._collect_lowered_body(command.body, context)

    def _collect_lowered_for(
        self,
        command: LoweredForCommand,
        context: _ExtractionContext,
    ) -> None:
        self._collect_lowered_body(command.start_body, context)
        self._collect_lowered_condition(command.condition, context)
        self._collect_lowered_body(command.next_body, context)
        self._collect_lowered_body(command.body, context)

    def _collect_info(self, command: Command, context: _ExtractionContext) -> None:
        if len(command.words) < 3:
            return
        if word_static_text(command.words[1]) != 'exists':
            return
        self._record_simple_reference_word(command.words[2], context)

    def _collect_lowered_if(
        self,
        command: LoweredIfCommand,
        context: _ExtractionContext,
    ) -> None:
        for clause in command.clauses:
            self._collect_lowered_condition(clause.condition, context)
            self._collect_lowered_body(clause.body, context)
        self._collect_lowered_body(command.else_body, context)

    def _collect_lowered_catch(
        self,
        command: LoweredCatchCommand,
        context: _ExtractionContext,
    ) -> None:
        self._collect_lowered_body(command.body, context)
        for variable_word in command.command.words[2:4]:
            self._record_simple_binding_word(variable_word, context, kind='catch')

    def _collect_global(self, command: Command, context: _ExtractionContext) -> None:
        if context.procedure_symbol_id is None:
            return

        for variable_word in command.words[1:]:
            link_details = self._variable_link_details(
                variable_word,
                context=context,
                namespace='::',
            )
            if link_details is None:
                continue
            local_name, target = link_details
            self._record_namespace_binding(
                target=target, span=variable_word.span, uri=context.uri, kind='global'
            )
            self._link_variable(context.scope_id, local_name, target)
            self._record_link_binding(
                local_name=local_name,
                span=variable_word.span,
                context=context,
                kind='global',
                target=target,
            )
            self._record_variable_reference(
                name=local_name,
                span=variable_word.span,
                context=context,
            )
            continue

        for variable_word in command.words[1:]:
            local_name = self._dynamic_link_local_name(variable_word)
            if local_name is None:
                continue
            self._record_variable_binding(
                name=local_name,
                span=variable_word.span,
                context=context,
                kind='global',
            )
            self._record_variable_reference(
                name=local_name,
                span=variable_word.span,
                context=context,
            )

    def _collect_variable(self, command: Command, context: _ExtractionContext) -> None:
        if len(command.words) < 2:
            return

        for variable_word in command.words[1::2]:
            link_details = self._variable_link_details(
                variable_word,
                context=context,
                namespace=context.namespace,
            )
            if link_details is None:
                continue
            local_name, target = link_details
            self._record_namespace_binding(
                target=target,
                span=variable_word.span,
                uri=context.uri,
                kind='variable',
            )
            if context.procedure_symbol_id is None:
                continue
            self._link_variable(context.scope_id, local_name, target)
            self._record_link_binding(
                local_name=local_name,
                span=variable_word.span,
                context=context,
                kind='variable',
                target=target,
            )
            self._record_variable_reference(
                name=local_name,
                span=variable_word.span,
                context=context,
            )
            continue

        if context.procedure_symbol_id is None:
            return

        for variable_word in command.words[1::2]:
            local_name = self._dynamic_link_local_name(variable_word)
            if local_name is None:
                continue
            self._record_variable_binding(
                name=local_name,
                span=variable_word.span,
                context=context,
                kind='variable',
            )
            self._record_variable_reference(
                name=local_name,
                span=variable_word.span,
                context=context,
            )

    def _collect_upvar(self, command: Command, context: _ExtractionContext) -> None:
        if context.procedure_symbol_id is None or len(command.words) < 3:
            return

        start_index = 1
        level = word_static_text(command.words[start_index])
        if level is not None and self._is_upvar_level(level):
            start_index += 1

        if start_index >= len(command.words) - 1:
            return

        for local_word in command.words[start_index + 1 :: 2]:
            self._record_simple_binding_word(local_word, context, kind='upvar')

    def _collect_lowered_switch(
        self,
        command: LoweredSwitchCommand,
        context: _ExtractionContext,
    ) -> None:
        self._collect_switch_regexp_bindings(command.regexp_binding_words, context)
        for body in command.branch_bodies:
            self._collect_lowered_body(body, context)

    def _collect_vwait(self, command: Command, context: _ExtractionContext) -> None:
        if len(command.words) < 2:
            return

        variable_name = self._simple_variable_name(command.words[1])
        if variable_name is None:
            return

        target = self._namespace_variable_target(
            name=variable_name,
            uri=context.uri,
            namespace='::',
        )
        self._record_custom_variable_reference(
            name=target.name,
            span=command.words[1].span,
            namespace=target.namespace,
            scope_id=target.scope_id,
            procedure_symbol_id=None,
            uri=context.uri,
        )

    def _collect_lowered_while(
        self,
        command: LoweredWhileCommand,
        context: _ExtractionContext,
    ) -> None:
        self._collect_lowered_condition(command.condition, context)
        self._collect_lowered_body(command.body, context)

    def _collect_lowered_body(
        self,
        body: LoweredScriptBody | None,
        context: _ExtractionContext,
    ) -> None:
        if body is None:
            return
        self._collect_lowered_script(body.script, context)

    def _collect_lowered_condition(
        self,
        condition: LoweredCondition | None,
        context: _ExtractionContext,
    ) -> None:
        if condition is None:
            return
        for substitution in condition.variable_substitutions:
            self._record_variable_reference(
                name=substitution.name,
                span=substitution.span,
                context=context,
            )
        for script in condition.command_substitutions:
            self._collect_lowered_script(script, context)

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

    def _record_variable_reference(
        self,
        name: str,
        span: Span,
        context: _ExtractionContext,
    ) -> None:
        name = _normalize_variable_name(name)
        if self._linked_variable(context.scope_id, name) is not None:
            self._record_custom_variable_reference(
                name=name,
                span=span,
                namespace=context.namespace,
                scope_id=context.scope_id,
                procedure_symbol_id=context.procedure_symbol_id,
                uri=context.uri,
            )
            return

        direct_target = self._direct_namespace_variable_target(
            name=name,
            uri=context.uri,
            namespace=context.namespace,
        )
        if direct_target is not None:
            self._record_custom_variable_reference(
                name=direct_target.name,
                span=span,
                namespace=direct_target.namespace,
                scope_id=direct_target.scope_id,
                procedure_symbol_id=None,
                uri=context.uri,
            )
            return

        self._record_custom_variable_reference(
            name=name,
            span=span,
            namespace=context.namespace,
            scope_id=context.scope_id,
            procedure_symbol_id=context.procedure_symbol_id,
            uri=context.uri,
        )

    def _record_variable_binding(
        self,
        name: str,
        span: Span,
        context: _ExtractionContext,
        kind: BindingKind,
    ) -> None:
        name = _normalize_variable_name(name)
        linked_target = self._linked_variable(context.scope_id, name)
        if linked_target is not None:
            self._record_custom_variable_binding(
                name=name,
                span=span,
                namespace=context.namespace,
                scope_id=context.scope_id,
                procedure_symbol_id=context.procedure_symbol_id,
                symbol_id=linked_target.symbol_id,
                uri=context.uri,
                kind=kind,
            )
            return

        direct_target = self._direct_namespace_variable_target(
            name=name,
            uri=context.uri,
            namespace=context.namespace,
        )
        if direct_target is not None:
            self._record_namespace_binding(
                target=direct_target, span=span, uri=context.uri, kind=kind
            )
            return

        self._record_custom_variable_binding(
            name=name,
            span=span,
            namespace=context.namespace,
            scope_id=context.scope_id,
            procedure_symbol_id=context.procedure_symbol_id,
            symbol_id=variable_symbol_id(context.uri, context.scope_id, name),
            uri=context.uri,
            kind=kind,
        )

    def _record_custom_variable_reference(
        self,
        *,
        name: str,
        span: Span,
        namespace: str,
        scope_id: str,
        procedure_symbol_id: str | None,
        uri: str,
    ) -> None:
        self._variable_references.append(
            VariableReference(
                uri=uri,
                name=name,
                namespace=namespace,
                scope_id=scope_id,
                procedure_symbol_id=procedure_symbol_id,
                span=span,
            )
        )

    def _record_custom_variable_binding(
        self,
        *,
        name: str,
        span: Span,
        namespace: str,
        scope_id: str,
        procedure_symbol_id: str | None,
        symbol_id: str,
        uri: str,
        kind: BindingKind,
    ) -> None:
        self._variable_bindings.append(
            VarBinding(
                symbol_id=symbol_id,
                uri=uri,
                name=name,
                scope_id=scope_id,
                namespace=namespace,
                procedure_symbol_id=procedure_symbol_id,
                kind=kind,
                span=span,
            )
        )

    def _record_namespace_binding(
        self,
        *,
        target: _VariableTarget,
        span: Span,
        uri: str,
        kind: BindingKind,
    ) -> None:
        self._record_custom_variable_binding(
            name=target.name,
            span=span,
            namespace=target.namespace,
            scope_id=target.scope_id,
            procedure_symbol_id=None,
            symbol_id=target.symbol_id,
            uri=uri,
            kind=kind,
        )

    def _simple_variable_name(self, word: Word) -> str | None:
        variable_name = word_static_text(word)
        if variable_name is None:
            return None
        variable_name = _normalize_variable_name(variable_name)
        if not is_simple_name(variable_name):
            return None
        return variable_name

    def _record_variable_writer(
        self,
        command: Command,
        context: _ExtractionContext,
        *,
        kind: BindingKind,
    ) -> None:
        if len(command.words) < 2:
            return
        self._record_simple_binding_word(command.words[1], context, kind=kind)

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

    def _regex_value_start_index(self, command: Command) -> int | None:
        index = 1
        while index < len(command.words):
            option = word_static_text(command.words[index])
            if option is None:
                return index
            if option == '--':
                return index + 1 if index + 1 < len(command.words) else None
            if option in {
                '-all',
                '-about',
                '-expanded',
                '-indices',
                '-inline',
                '-line',
                '-lineanchor',
                '-linestop',
                '-nocase',
            }:
                index += 1
                continue
            if option == '-start':
                if index + 1 >= len(command.words):
                    return None
                index += 2
                continue
            if option.startswith('-'):
                return None
            return index
        return None

    def _record_simple_reference_word(self, word: Word, context: _ExtractionContext) -> None:
        variable_name = self._simple_variable_name(word)
        if variable_name is None:
            return
        self._record_variable_reference(
            name=variable_name,
            span=word.span,
            context=context,
        )

    def _link_variable(self, scope_id: str, local_name: str, target: _VariableTarget) -> None:
        self._linked_variables_by_scope.setdefault(scope_id, {})[local_name] = target

    def _linked_variable(self, scope_id: str, name: str) -> _VariableTarget | None:
        return self._linked_variables_by_scope.get(scope_id, {}).get(name)

    def _direct_namespace_variable_target(
        self,
        *,
        name: str,
        uri: str,
        namespace: str,
    ) -> _VariableTarget | None:
        if '::' not in name:
            return None
        return self._namespace_variable_target(name=name, uri=uri, namespace=namespace)

    def _namespace_variable_target(
        self,
        *,
        name: str,
        uri: str,
        namespace: str,
    ) -> _VariableTarget:
        qualified_name = qualify_name(name, namespace)
        target_namespace = namespace_for_name(qualified_name)
        target_name = name_tail(qualified_name)
        scope_id = namespace_scope_id(target_namespace)
        return _VariableTarget(
            name=target_name,
            namespace=target_namespace,
            scope_id=scope_id,
            symbol_id=variable_symbol_id(uri, scope_id, target_name),
        )

    def _variable_link_details(
        self,
        word: Word,
        *,
        context: _ExtractionContext,
        namespace: str,
    ) -> tuple[str, _VariableTarget] | None:
        variable_name = self._simple_variable_name(word)
        if variable_name is None:
            return None
        return (
            name_tail(variable_name),
            self._namespace_variable_target(
                name=variable_name,
                uri=context.uri,
                namespace=namespace,
            ),
        )

    def _record_link_binding(
        self,
        *,
        local_name: str,
        span: Span,
        context: _ExtractionContext,
        kind: BindingKind,
        target: _VariableTarget,
    ) -> None:
        self._record_custom_variable_binding(
            name=local_name,
            span=span,
            namespace=context.namespace,
            scope_id=context.scope_id,
            procedure_symbol_id=context.procedure_symbol_id,
            symbol_id=target.symbol_id,
            uri=context.uri,
            kind=kind,
        )

    def _dynamic_link_local_name(self, word: Word) -> str | None:
        if isinstance(word, BracedWord):
            return None

        saw_variable_substitution = False
        literal_suffix: list[str] = []
        for part in word.parts:
            if isinstance(part, CommandSubstitution):
                return None
            if isinstance(part, VariableSubstitution):
                saw_variable_substitution = True
                continue
            literal_suffix.append(part.text)

        if not saw_variable_substitution:
            return None

        suffix = ''.join(literal_suffix)
        if '::' not in suffix:
            return None

        local_name = suffix.rsplit('::', 1)[-1]
        if not is_simple_name(local_name):
            return None
        return local_name

    def _exact_command_import(
        self,
        pattern: str,
        current_namespace: str,
    ) -> tuple[str, str] | None:
        if '*' in pattern:
            return None

        qualified_name = qualify_name(pattern, current_namespace)
        return name_tail(qualified_name), qualified_name

    def _wildcard_import_namespace(
        self,
        pattern: str,
        current_namespace: str,
    ) -> str | None:
        if not pattern.endswith('::*') or pattern.count('*') != 1:
            return None

        namespace = pattern.removesuffix('::*')
        if not namespace:
            return None

        return qualify_namespace(namespace, current_namespace)

    def _is_upvar_level(self, value: str) -> bool:
        return value.isdigit() or (value.startswith('#') and value[1:].isdigit())

    def _parameter_decls_from_items(
        self,
        items: tuple[ListItem, ...],
        *,
        uri: str,
        proc_symbol_id: str,
    ) -> tuple[ParameterDecl, ...]:
        parameters: list[ParameterDecl] = []
        for item in items:
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

    def _collect_switch_regexp_bindings(
        self,
        binding_words: tuple[Word, ...],
        context: _ExtractionContext,
    ) -> None:
        for binding_word in binding_words:
            self._record_simple_binding_word(binding_word, context, kind='switch')

    def _record_list_item_bindings(
        self,
        items: tuple[ListItem, ...] | list[ListItem],
        *,
        context: _ExtractionContext,
        kind: BindingKind,
    ) -> None:
        for item in items:
            if not is_simple_name(item.text):
                continue
            self._record_variable_binding(
                name=item.text,
                span=item.span,
                context=context,
                kind=kind,
            )

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


def _normalize_variable_name(name: str) -> str:
    while name.endswith(':') and not name.endswith('::'):
        name = name[:-1]

    open_paren = name.find('(')
    if open_paren <= 0 or not name.endswith(')'):
        return name

    base_name = name[:open_paren]
    if not is_simple_name(base_name):
        return name
    return base_name
