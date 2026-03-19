from __future__ import annotations

from dataclasses import dataclass

from tcl_lsp.analysis.arity import proc_parameter_arity
from tcl_lsp.analysis.builtins import (
    annotated_metadata_commands_for_packages,
    builtin_command_for_packages,
    canonical_builtin_package_name,
    is_builtin_package,
)
from tcl_lsp.analysis.embedded_languages import (
    EmbeddedLanguageEntry,
    EmbeddedLanguageName,
    match_embedded_language_command,
    match_embedded_language_entry,
)
from tcl_lsp.analysis.facts.lowering import (
    LoweredCatchCommand,
    LoweredCommand,
    LoweredCondition,
    LoweredForCommand,
    LoweredGenericCommand,
    LoweredIfCommand,
    LoweredNamespaceEvalCommand,
    LoweredProcCommand,
    LoweredScript,
    LoweredScriptBody,
    LoweredSwitchCommand,
    LoweredTryCommand,
    LoweredWhileCommand,
    LoweredWordReferences,
    lower_parse_result,
    lower_script,
)
from tcl_lsp.analysis.facts.parsing import ListItem, is_simple_name, split_tcl_list
from tcl_lsp.analysis.facts.utils import (
    body_span,
    command_documentation,
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
from tcl_lsp.analysis.flow import (
    VariableFlowState,
    condition_branch_flow_states,
    dynamic_variable_target_names,
    exact_word_values,
    normalize_variable_name,
    script_body_flow_state,
    state_with_set_command,
    state_with_unset_command,
    switch_branch_flow_state,
    unset_target_words,
)
from tcl_lsp.analysis.metadata_commands import (
    MetadataBind,
    MetadataCommand,
    MetadataPlugin,
    MetadataProcedure,
    MetadataRef,
    MetadataScriptBody,
    select_argument_indices,
)
from tcl_lsp.analysis.model import (
    BINDING_KINDS,
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
from tcl_lsp.common import Diagnostic, DocumentSymbol, Position, Span
from tcl_lsp.metadata_paths import DEFAULT_METADATA_REGISTRY, MetadataRegistry
from tcl_lsp.parser import Parser, word_static_text
from tcl_lsp.parser.model import (
    BracedWord,
    Command,
    CommandSubstitution,
    LiteralText,
    ParseResult,
    Script,
    VariableSubstitution,
    Word,
)
from tcl_lsp.plugins.host import PluginProcedureEffect, TclPluginHost


@dataclass(frozen=True, slots=True)
class _ExtractionContext:
    uri: str
    namespace: str
    scope_id: str
    procedure_symbol_id: str | None
    embedded_language: EmbeddedLanguageName | None
    embedded_owner_name: str | None
    flow_state: VariableFlowState


@dataclass(frozen=True, slots=True)
class _VariableTarget:
    name: str
    namespace: str
    scope_id: str
    symbol_id: str


class FactExtractor:
    __slots__ = ('_metadata_registry', '_parser', '_plugin_host')

    def __init__(
        self,
        parser: Parser | None = None,
        plugin_host: TclPluginHost | None = None,
        *,
        metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
    ) -> None:
        self._parser = Parser() if parser is None else parser
        self._metadata_registry = metadata_registry
        self._plugin_host = TclPluginHost() if plugin_host is None else plugin_host

    @property
    def metadata_registry(self) -> MetadataRegistry:
        return self._metadata_registry

    def close(self) -> None:
        self._plugin_host.close()

    def extract(
        self,
        parse_result: ParseResult,
        *,
        include_parse_result: bool = True,
        include_lexical_spans: bool | None = None,
    ) -> DocumentFacts:
        if include_lexical_spans is None:
            include_lexical_spans = include_parse_result

        lowering_result = lower_parse_result(
            parse_result,
            parser=self._parser,
            collect_lexical_spans=include_lexical_spans,
        )
        collector = _FactCollector(
            metadata_registry=self._metadata_registry,
            parser=self._parser,
            plugin_host=self._plugin_host,
            parse_result=parse_result,
            comment_spans=lowering_result.comment_spans,
            operator_spans=lowering_result.operator_spans,
            string_spans=lowering_result.string_spans,
            lowered_script=lowering_result.script,
            diagnostics=parse_result.diagnostics + lowering_result.diagnostics,
            include_parse_result=include_parse_result,
            include_lexical_spans=include_lexical_spans,
        )
        return collector.collect()


class _FactCollector:
    __slots__ = (
        '_active_builtin_packages',
        '_command_calls',
        '_command_imports',
        '_comment_spans',
        '_diagnostics',
        '_include_lexical_spans',
        '_include_parse_result',
        '_linked_variables_by_scope',
        '_lowered_script',
        '_metadata_registry',
        '_namespaces',
        '_operator_spans',
        '_package_index_entries',
        '_package_provides',
        '_package_requires',
        '_parse_result',
        '_parser',
        '_plugin_host',
        '_procedures',
        '_source_directives',
        '_string_spans',
        '_variable_bindings',
        '_variable_references',
    )

    def __init__(
        self,
        metadata_registry: MetadataRegistry,
        parser: Parser,
        plugin_host: TclPluginHost,
        parse_result: ParseResult,
        *,
        comment_spans: tuple[Span, ...],
        operator_spans: tuple[Span, ...],
        string_spans: tuple[Span, ...],
        lowered_script: LoweredScript,
        diagnostics: tuple[Diagnostic, ...],
        include_lexical_spans: bool,
        include_parse_result: bool,
    ) -> None:
        self._metadata_registry = metadata_registry
        self._parser = parser
        self._plugin_host = plugin_host
        self._parse_result = parse_result
        self._lowered_script = lowered_script
        self._include_lexical_spans = include_lexical_spans
        self._include_parse_result = include_parse_result
        self._diagnostics: list[Diagnostic] = list(diagnostics)
        self._active_builtin_packages: set[str] = set()
        self._comment_spans: list[Span] = list(comment_spans)
        self._string_spans: list[Span] = list(string_spans)
        self._operator_spans: list[Span] = list(operator_spans)
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

    def collect(self) -> DocumentFacts:
        root_context = self._namespace_context(self._parse_result.source_id, '::')
        self._collect_lowered_script(self._lowered_script, root_context)
        return DocumentFacts(
            uri=self._parse_result.source_id,
            parse_result=self._parse_result if self._include_parse_result else None,
            comment_spans=tuple(self._comment_spans),
            string_spans=tuple(self._string_spans),
            operator_spans=tuple(self._operator_spans),
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

    def _collect_lowered_script(
        self,
        script: LoweredScript,
        context: _ExtractionContext,
    ) -> _ExtractionContext:
        current_context = context
        for command in script.commands:
            current_context = self._collect_lowered_command(command, current_context)
        return current_context

    def _collect_lowered_command(
        self, command: LoweredCommand, context: _ExtractionContext
    ) -> _ExtractionContext:
        syntax_command = command.command
        command_name = self._collect_command_common(command, context)
        if type(command) is not LoweredGenericCommand and self._collect_special_lowered_command(
            command, context
        ):
            return context
        if self._collect_embedded_language_command(syntax_command, context):
            return context
        if self._collect_embedded_language_entry(syntax_command, context):
            return context

        normalized_command_name = (
            normalize_command_name(command_name) if command_name is not None else None
        )
        self._collect_builtin_handler_command(
            syntax_command,
            normalized_command_name,
            context,
        )
        return self._updated_context_after_command(
            syntax_command,
            normalized_command_name=normalized_command_name,
            context=context,
        )

    def _collect_special_lowered_command(
        self,
        command: LoweredCommand,
        context: _ExtractionContext,
    ) -> bool:
        if isinstance(command, LoweredProcCommand):
            self._collect_lowered_proc(command, context)
        elif isinstance(command, LoweredNamespaceEvalCommand):
            self._collect_lowered_namespace_eval(command, context)
        elif isinstance(command, LoweredForCommand):
            self._collect_lowered_for(command, context)
        elif isinstance(command, LoweredIfCommand):
            self._collect_lowered_if(command, context)
        elif isinstance(command, LoweredCatchCommand):
            self._collect_lowered_catch(command, context)
        elif isinstance(command, LoweredTryCommand):
            self._collect_lowered_try(command, context)
        elif isinstance(command, LoweredSwitchCommand):
            self._collect_lowered_switch(command, context)
        elif isinstance(command, LoweredWhileCommand):
            self._collect_lowered_while(command, context)
        else:
            return False
        return True

    def _collect_builtin_handler_command(
        self,
        command: Command,
        normalized_command_name: str | None,
        context: _ExtractionContext,
    ) -> None:
        match normalized_command_name:
            case 'array':
                self._collect_array(command, context)
            case 'binary':
                self._collect_binary(command, context)
            case 'package':
                self._collect_package(command, context)
            case 'namespace':
                self._collect_namespace(command, context)
            case 'set':
                self._collect_set(command, context)
            case 'global':
                self._collect_global(command, context)
            case 'info':
                self._collect_info(command, context)
            case 'source':
                self._collect_source(command, context)
            case 'unset':
                self._collect_unset(command, context)
            case 'upvar':
                self._collect_upvar(command, context)
            case 'variable':
                self._collect_variable(command, context)
            case 'vwait':
                self._collect_vwait(command, context)
            case _:
                pass

    def _collect_command_common(
        self,
        command: LoweredCommand,
        context: _ExtractionContext,
    ) -> str | None:
        syntax_command = command.command
        if not syntax_command.words:
            return None

        command_name_word = syntax_command.words[0]
        argument_words = syntax_command.words[1:]
        self._record_command_call(
            command_name=command.command_name,
            command_span=syntax_command.span,
            name_span=command_name_word.span,
            arg_texts=tuple(word_static_text(word) for word in argument_words),
            arg_spans=tuple(word.span for word in argument_words),
            arg_expanded=tuple(word.expanded for word in argument_words),
            context=context,
        )

        for word_references in command.word_references:
            self._collect_lowered_word_references(word_references, context)

        self._collect_builtin_subcommands(syntax_command, context)
        self._collect_metadata_command_annotations(syntax_command, context)
        return command.command_name

    def _record_command_call(
        self,
        command_name: str | None,
        command_span: Span,
        name_span: Span,
        arg_texts: tuple[str | None, ...],
        arg_spans: tuple[Span, ...],
        arg_expanded: tuple[bool, ...],
        context: _ExtractionContext,
    ) -> None:
        self._command_calls.append(
            CommandCall(
                uri=context.uri,
                name=command_name,
                arg_texts=arg_texts,
                arg_spans=arg_spans,
                arg_expanded=arg_expanded,
                namespace=context.namespace,
                scope_id=context.scope_id,
                procedure_symbol_id=context.procedure_symbol_id,
                embedded_language=context.embedded_language,
                span=command_span,
                name_span=name_span,
                dynamic=command_name is None,
            )
        )

    def _collect_builtin_subcommands(self, command: Command, context: _ExtractionContext) -> None:
        required_packages = frozenset(self._active_builtin_packages)
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
            if (
                builtin_command_for_packages(
                    builtin_name,
                    required_packages,
                    metadata_registry=self._metadata_registry,
                )
                is None
            ):
                continue

            argument_words = command.words[index + 1 :]
            self._record_command_call(
                command_name=builtin_name,
                command_span=command.span,
                name_span=word.content_span,
                arg_texts=tuple(word_static_text(argument) for argument in argument_words),
                arg_spans=tuple(argument.span for argument in argument_words),
                arg_expanded=tuple(argument.expanded for argument in argument_words),
                context=context,
            )

    def _collect_metadata_command_annotations(
        self,
        command: Command,
        context: _ExtractionContext,
    ) -> None:
        matched_command = self._matched_metadata_command(command, context)
        if matched_command is None:
            return

        metadata_command, prefix_word_count = matched_command
        for annotation in metadata_command.annotations:
            if not isinstance(annotation, MetadataProcedure):
                if isinstance(annotation, MetadataPlugin):
                    self._collect_metadata_plugin(
                        command,
                        context,
                        metadata_command=metadata_command,
                        prefix_word_count=prefix_word_count,
                        plugin=annotation,
                    )
                continue
            self._collect_metadata_procedure(
                command,
                context,
                command_name=metadata_command.name,
                prefix_word_count=prefix_word_count,
                procedure=annotation,
            )
        self._collect_selected_metadata_annotations(
            command,
            context,
            metadata_command=metadata_command,
            prefix_word_count=prefix_word_count,
        )

    def _collect_embedded_language_command(
        self,
        command: Command,
        context: _ExtractionContext,
    ) -> bool:
        matched = match_embedded_language_command(
            command,
            context.embedded_language,
            metadata_registry=self._metadata_registry,
        )
        if matched is None:
            return False

        handled = False
        for annotation in matched.metadata_command.annotations:
            if not isinstance(annotation, MetadataProcedure):
                continue
            self._collect_embedded_procedure(
                command,
                context,
                command_name=matched.metadata_command.name,
                prefix_word_count=matched.prefix_word_count,
                procedure=annotation,
            )
            handled = True

        handled |= self._collect_selected_metadata_annotations(
            command,
            context,
            metadata_command=matched.metadata_command,
            prefix_word_count=matched.prefix_word_count,
        )
        return handled

    def _collect_metadata_plugin(
        self,
        command: Command,
        context: _ExtractionContext,
        *,
        metadata_command: MetadataCommand,
        prefix_word_count: int,
        plugin: MetadataPlugin,
    ) -> None:
        word_texts, static_flags = self._plugin_word_texts(command.words)
        effects = self._plugin_host.call_plugin(
            plugin,
            words=word_texts,
            info={
                'embedded-language': context.embedded_language or '',
                'embedded-owner-name': context.embedded_owner_name or '',
                'metadata-command': metadata_command.name,
                'namespace': context.namespace,
                'prefix-word-count': str(prefix_word_count),
                'procedure-symbol-id': context.procedure_symbol_id or '',
                'scope-id': context.scope_id,
                'static-flags': self._plugin_flag_list(static_flags),
                'expanded-flags': self._plugin_flag_list(
                    tuple(word.expanded for word in command.words)
                ),
                'uri': context.uri,
            },
        )
        for effect in effects:
            self._collect_plugin_procedure(command, context, effect)

    def _collect_metadata_procedure(
        self,
        command: Command,
        context: _ExtractionContext,
        *,
        command_name: str,
        prefix_word_count: int,
        procedure: MetadataProcedure,
    ) -> None:
        argument_words = command.words[prefix_word_count:]
        procedure_name, selection_span = self._procedure_name(
            command,
            command_name=command_name,
            prefix_word_count=prefix_word_count,
            argument_words=argument_words,
            procedure=procedure,
        )
        if procedure_name is None or selection_span is None:
            return

        parameter_items = self._procedure_parameter_items(argument_words, procedure)
        if parameter_items is None:
            return

        if procedure.body_index >= len(argument_words):
            return
        body_word = argument_words[procedure.body_index]
        body = self._embedded_script_text(body_word)
        if body is None:
            return

        qualified_name = qualify_name(procedure_name, context.namespace)
        proc_id = proc_symbol_id(context.uri, qualified_name, selection_span.start.offset)
        proc_decl = ProcDecl(
            symbol_id=proc_id,
            uri=context.uri,
            name=procedure_name,
            qualified_name=qualified_name,
            namespace=namespace_for_name(qualified_name),
            span=command.span,
            name_span=selection_span,
            parameters=self._parameter_decls_from_items(
                parameter_items,
                uri=context.uri,
                proc_symbol_id=proc_id,
            ),
            arity=proc_parameter_arity(parameter_items),
            documentation=command_documentation(command),
            body_span=body_span(body_word),
        )
        self._procedures.append(proc_decl)

        body_context = _ExtractionContext(
            uri=proc_decl.uri,
            namespace=proc_decl.namespace,
            scope_id=proc_decl.symbol_id,
            procedure_symbol_id=proc_decl.symbol_id,
            embedded_language=procedure.body_context,
            embedded_owner_name=None,
            flow_state=VariableFlowState.empty(),
        )
        self._record_parameter_bindings(proc_decl.parameters, body_context)
        self._collect_script_body_word(body_word, body_context)

    def _collect_plugin_procedure(
        self,
        command: Command,
        context: _ExtractionContext,
        effect: PluginProcedureEffect,
    ) -> None:
        if effect.name_word_index >= len(command.words):
            return

        name_word = command.words[effect.name_word_index]
        procedure_name = word_static_text(name_word)
        if procedure_name is None:
            return

        body_word: Word | None = None
        if effect.body_word_index is not None:
            if effect.body_word_index >= len(command.words):
                return
            body_word = command.words[effect.body_word_index]
            if self._embedded_script_text(body_word) is None:
                return

        qualified_name = qualify_name(procedure_name, context.namespace)
        proc_id = proc_symbol_id(context.uri, qualified_name, name_word.content_span.start.offset)
        proc_decl = ProcDecl(
            symbol_id=proc_id,
            uri=context.uri,
            name=procedure_name,
            qualified_name=qualified_name,
            namespace=namespace_for_name(qualified_name),
            span=command.span,
            name_span=name_word.content_span,
            parameters=self._parameter_decls_from_plugin_names(
                effect.parameter_names,
                source_span=(
                    command.words[effect.parameter_word_index].content_span
                    if effect.parameter_word_index is not None
                    and effect.parameter_word_index < len(command.words)
                    else name_word.content_span
                ),
                uri=context.uri,
                proc_symbol_id=proc_id,
            ),
            arity=None,
            documentation=command_documentation(command),
            body_span=body_span(body_word) if body_word is not None else None,
        )
        self._procedures.append(proc_decl)

        if body_word is None:
            return

        body_context = _ExtractionContext(
            uri=proc_decl.uri,
            namespace=proc_decl.namespace,
            scope_id=proc_decl.symbol_id,
            procedure_symbol_id=proc_decl.symbol_id,
            embedded_language=effect.body_context,
            embedded_owner_name=None,
            flow_state=VariableFlowState.empty(),
        )
        self._record_parameter_bindings(proc_decl.parameters, body_context)
        self._collect_script_body_word(body_word, body_context)

    def _collect_embedded_language_entry(
        self,
        command: Command,
        context: _ExtractionContext,
    ) -> bool:
        entry = match_embedded_language_entry(
            command,
            current_namespace=context.namespace,
            metadata_registry=self._metadata_registry,
        )
        if entry is None:
            return False

        entry_context = self._embedded_language_context(entry, parent_context=context)
        handled = False
        if entry.script_word_index is not None and entry.script_word_index < len(command.words):
            self._collect_script_body_word(command.words[entry.script_word_index], entry_context)
            handled = True
        if entry.inline_command_start_index is not None and entry.inline_command_start_index < len(
            command.words
        ):
            self._collect_inline_embedded_command(
                command.words[entry.inline_command_start_index :],
                entry_context,
            )
            handled = True
        return handled

    def _embedded_language_context(
        self,
        entry: EmbeddedLanguageEntry,
        *,
        parent_context: _ExtractionContext,
    ) -> _ExtractionContext:
        return _ExtractionContext(
            uri=parent_context.uri,
            namespace=entry.namespace,
            scope_id=parent_context.scope_id,
            procedure_symbol_id=parent_context.procedure_symbol_id,
            embedded_language=entry.language,
            embedded_owner_name=entry.owner_name,
            flow_state=parent_context.flow_state,
        )

    def _collect_inline_embedded_command(
        self,
        words: tuple[Word, ...],
        context: _ExtractionContext,
    ) -> None:
        if not words:
            return

        embedded_command = Command(
            span=Span(start=words[0].span.start, end=words[-1].span.end),
            words=words,
        )
        lowering_result = lower_script(
            Script(span=embedded_command.span, commands=(embedded_command,)),
            parser=self._parser,
            source_id=context.uri,
            collect_lexical_spans=self._include_lexical_spans,
        )
        self._comment_spans.extend(lowering_result.comment_spans)
        self._string_spans.extend(lowering_result.string_spans)
        self._operator_spans.extend(lowering_result.operator_spans)
        self._diagnostics.extend(lowering_result.diagnostics)
        self._collect_lowered_script(lowering_result.script, context)

    def _collect_embedded_procedure(
        self,
        command: Command,
        context: _ExtractionContext,
        *,
        command_name: str,
        prefix_word_count: int,
        procedure: MetadataProcedure,
    ) -> None:
        owner_name = context.embedded_owner_name
        if owner_name is None:
            return

        argument_words = command.words[prefix_word_count:]
        procedure_name, selection_span = self._procedure_name(
            command,
            command_name=command_name,
            prefix_word_count=prefix_word_count,
            argument_words=argument_words,
            procedure=procedure,
        )
        if procedure_name is None or selection_span is None:
            return

        parameter_items = self._procedure_parameter_items(argument_words, procedure)
        if parameter_items is None:
            return

        if procedure.body_index >= len(argument_words):
            return
        body_word = argument_words[procedure.body_index]
        body = self._embedded_script_text(body_word)
        if body is None:
            return

        qualified_name = self._embedded_procedure_qualified_name(
            owner_name=owner_name,
            command_name=command_name,
            procedure=procedure,
            procedure_name=procedure_name,
        )
        proc_id = proc_symbol_id(context.uri, qualified_name, selection_span.start.offset)
        proc_decl = ProcDecl(
            symbol_id=proc_id,
            uri=context.uri,
            name=procedure_name,
            qualified_name=qualified_name,
            namespace=namespace_for_name(owner_name),
            span=command.span,
            name_span=selection_span,
            parameters=self._parameter_decls_from_items(
                parameter_items,
                uri=context.uri,
                proc_symbol_id=proc_id,
            ),
            arity=proc_parameter_arity(parameter_items),
            documentation=command_documentation(command),
            body_span=body_span(body_word),
        )
        self._procedures.append(proc_decl)

        body_context = _ExtractionContext(
            uri=proc_decl.uri,
            namespace=proc_decl.namespace,
            scope_id=proc_decl.symbol_id,
            procedure_symbol_id=proc_decl.symbol_id,
            embedded_language=procedure.body_context,
            embedded_owner_name=owner_name,
            flow_state=VariableFlowState.empty(),
        )
        self._record_parameter_bindings(proc_decl.parameters, body_context)
        self._collect_script_body_word(body_word, body_context)

    def _collect_selected_metadata_annotations(
        self,
        command: Command,
        context: _ExtractionContext,
        *,
        metadata_command: MetadataCommand,
        prefix_word_count: int,
    ) -> bool:
        argument_words = command.words[prefix_word_count:]
        argument_texts = tuple(word_static_text(word) for word in argument_words)
        handled = False
        for annotation in metadata_command.annotations:
            if not isinstance(annotation, (MetadataBind, MetadataRef, MetadataScriptBody)):
                continue
            selected_words = self._selected_metadata_argument_words(
                argument_words=argument_words,
                argument_texts=argument_texts,
                metadata_command=metadata_command,
                annotation=annotation,
            )
            if selected_words is None:
                continue

            handled = True
            if isinstance(annotation, MetadataBind):
                binding_kind = self._metadata_binding_kind(metadata_command, annotation)
                for selected_word in selected_words:
                    if annotation.selector.list_mode:
                        self._record_list_binding_word(selected_word, context, kind=binding_kind)
                        continue
                    self._record_simple_binding_word(selected_word, context, kind=binding_kind)
                continue

            if isinstance(annotation, MetadataRef):
                for selected_word in selected_words:
                    if annotation.selector.list_mode:
                        self._record_list_reference_word(selected_word, context)
                        continue
                    self._record_simple_reference_word(selected_word, context)
                continue

            for selected_word in selected_words:
                self._collect_script_body_word(
                    selected_word,
                    self._metadata_script_body_context(
                        command,
                        context,
                        metadata_command=metadata_command,
                        prefix_word_count=prefix_word_count,
                        selected_word=selected_word,
                    ),
                )

        return handled

    def _metadata_script_body_context(
        self,
        command: Command,
        context: _ExtractionContext,
        *,
        metadata_command: MetadataCommand,
        prefix_word_count: int,
        selected_word: Word,
    ) -> _ExtractionContext:
        argument_words = command.words[prefix_word_count:]
        next_flow_state = script_body_flow_state(
            context.flow_state,
            metadata_command_name=metadata_command.name,
            argument_words=argument_words,
            selected_word=selected_word,
        )
        return self._context_with_flow_state(context, next_flow_state)

    def _procedure_name(
        self,
        command: Command,
        *,
        command_name: str,
        prefix_word_count: int,
        argument_words: tuple[Word, ...],
        procedure: MetadataProcedure,
    ) -> tuple[str | None, Span | None]:
        if procedure.member_name_index is None:
            return command_name.rsplit(' ', maxsplit=1)[-1], command.words[
                prefix_word_count - 1
            ].content_span

        if procedure.member_name_index >= len(argument_words):
            return None, None
        name_word = argument_words[procedure.member_name_index]
        name = word_static_text(name_word)
        if name is None:
            return None, None
        return name, name_word.content_span

    def _procedure_parameter_items(
        self,
        argument_words: tuple[Word, ...],
        procedure: MetadataProcedure,
    ) -> tuple[ListItem, ...] | None:
        if procedure.parameter_index is None:
            return ()
        if procedure.parameter_index >= len(argument_words):
            return None

        parameter_word = argument_words[procedure.parameter_index]
        static_text = self._static_list_text(parameter_word)
        if static_text is None:
            return None
        return tuple(split_tcl_list(static_text, parameter_word.content_span.start))

    def _embedded_procedure_qualified_name(
        self,
        *,
        owner_name: str,
        command_name: str,
        procedure: MetadataProcedure,
        procedure_name: str,
    ) -> str:
        if procedure.member_name_index is None:
            return f'{owner_name} {command_name}'
        return f'{owner_name} {command_name} {procedure_name}'

    def _metadata_binding_kind(
        self,
        metadata_command: MetadataCommand,
        annotation: MetadataBind,
    ) -> BindingKind:
        if annotation.kind is not None:
            return annotation.kind

        inferred_kind = name_tail(metadata_command.name.rsplit(' ', 1)[-1])
        if inferred_kind not in BINDING_KINDS:
            raise RuntimeError(
                f'Metadata command `{metadata_command.name}` requires an explicit binding kind.'
            )
        return inferred_kind

    def _matched_metadata_command(
        self,
        command: Command,
        context: _ExtractionContext,
    ) -> tuple[MetadataCommand, int] | None:
        available_commands = annotated_metadata_commands_for_packages(
            frozenset(self._active_builtin_packages),
            metadata_registry=self._metadata_registry,
        )
        static_prefix_parts: list[str] = []
        imported_prefix_parts: list[list[str]] | None = None
        matched: tuple[MetadataCommand, int] | None = None
        for index, word in enumerate(command.words):
            static_text = word_static_text(word)
            if static_text is None:
                break
            if index == 0:
                static_text = normalize_command_name(static_text)
            static_prefix_parts.append(static_text)

            if index == 0:
                imported_prefix_parts = [
                    [normalize_command_name(target_name)]
                    for target_name in self._imported_command_candidates(
                        static_text,
                        context.namespace,
                    )
                ]
            elif imported_prefix_parts is not None:
                for prefix_parts in imported_prefix_parts:
                    prefix_parts.append(static_text)

            metadata_command = self._unique_metadata_command(
                available_commands.get(' '.join(static_prefix_parts), ())
            )
            if metadata_command is not None:
                matched = metadata_command, index + 1
            if imported_prefix_parts is None:
                continue
            for prefix_parts in imported_prefix_parts:
                metadata_command = self._unique_metadata_command(
                    available_commands.get(' '.join(prefix_parts), ())
                )
                if metadata_command is not None:
                    matched = metadata_command, index + 1
        return matched

    def _unique_metadata_command(
        self,
        candidates: tuple[MetadataCommand, ...],
    ) -> MetadataCommand | None:
        if len(candidates) != 1:
            return None
        return candidates[0]

    def _imported_command_candidates(
        self,
        raw_name: str,
        namespace: str,
    ) -> tuple[str, ...]:
        if raw_name.startswith('::'):
            return ()

        candidates: dict[str, None] = {}
        for candidate_namespace in self._namespace_candidates(namespace):
            for command_import in self._command_imports:
                if command_import.namespace != candidate_namespace:
                    continue
                target_name = self._import_target_name(command_import, raw_name)
                if target_name is None:
                    continue
                candidates.setdefault(target_name, None)
        return tuple(candidates)

    def _namespace_candidates(self, namespace: str) -> tuple[str, ...]:
        if namespace == '::':
            return ('::',)

        namespace_segments = [segment for segment in namespace.split('::') if segment]
        candidates: list[str] = []
        while namespace_segments:
            candidates.append('::' + '::'.join(namespace_segments))
            namespace_segments = namespace_segments[:-1]
        candidates.append('::')
        return tuple(candidates)

    def _import_target_name(self, command_import: CommandImport, raw_name: str) -> str | None:
        if command_import.kind == 'exact':
            if command_import.imported_name != raw_name:
                return None
            return command_import.target_name

        if command_import.target_name == '::':
            return f'::{raw_name}'
        return f'{command_import.target_name}::{raw_name}'

    def _selected_metadata_argument_words(
        self,
        *,
        argument_words: tuple[Word, ...],
        argument_texts: tuple[str | None, ...],
        metadata_command: MetadataCommand,
        annotation: MetadataBind | MetadataRef | MetadataScriptBody,
    ) -> tuple[Word, ...] | None:
        selected_indices = select_argument_indices(
            annotation.selector,
            argument_texts,
            metadata_command.options,
            tuple(word.expanded for word in argument_words),
        )
        if selected_indices is None:
            return None
        return tuple(
            argument_words[index] for index in selected_indices if index < len(argument_words)
        )

    def _record_list_binding_word(
        self,
        word: Word,
        context: _ExtractionContext,
        *,
        kind: BindingKind,
    ) -> None:
        for item in self._static_list_items(word):
            if not is_simple_name(item.text):
                continue
            self._record_variable_binding(
                name=item.text,
                span=item.span,
                context=context,
                kind=kind,
            )

    def _record_list_reference_word(self, word: Word, context: _ExtractionContext) -> None:
        for item in self._static_list_items(word):
            if not is_simple_name(item.text):
                continue
            self._record_variable_reference(
                name=item.text,
                span=item.span,
                context=context,
            )

    def _static_list_items(self, word: Word) -> tuple[ListItem, ...]:
        static_text = self._static_list_text(word)
        if static_text is None:
            return ()
        return tuple(split_tcl_list(static_text, word.content_span.start))

    def _static_list_text(self, word: Word) -> str | None:
        if isinstance(word, BracedWord) and not word.expanded:
            raw_text = word.raw_text
            if raw_text.startswith('{'):
                raw_text = raw_text[1:]
            if raw_text.endswith('}'):
                raw_text = raw_text[:-1]
            return raw_text
        return word_static_text(word)

    def _collect_script_body_word(self, word: Word, context: _ExtractionContext) -> None:
        embedded_script_text = self._embedded_script_text(word)
        if embedded_script_text is None:
            return

        script_text, start_position = embedded_script_text
        if not self._include_lexical_spans:
            script = self._parser.parse_embedded_script_for_analysis(
                context.uri,
                script_text,
                start_position,
                diagnostics=self._diagnostics,
            )
            lowering_result = lower_script(
                script,
                parser=self._parser,
                source_id=context.uri,
                collect_lexical_spans=False,
            )
        else:
            parse_result = self._parser.parse_embedded_script(
                context.uri,
                script_text,
                start_position,
            )
            lowering_result = lower_parse_result(
                parse_result,
                parser=self._parser,
                collect_lexical_spans=True,
            )
            self._diagnostics.extend(parse_result.diagnostics)

        self._comment_spans.extend(lowering_result.comment_spans)
        self._string_spans.extend(lowering_result.string_spans)
        self._operator_spans.extend(lowering_result.operator_spans)
        self._diagnostics.extend(lowering_result.diagnostics)
        self._collect_lowered_script(lowering_result.script, context)

    def _embedded_script_text(self, word: Word) -> tuple[str, Position] | None:
        if isinstance(word, BracedWord) and not word.expanded:
            raw_text = word.raw_text
            if raw_text.startswith('{'):
                raw_text = raw_text[1:]
            if raw_text.endswith('}'):
                raw_text = raw_text[:-1]
            return raw_text, word.content_span.start

        static_text = word_static_text(word)
        if static_text is None:
            return None
        return static_text, word.content_span.start

    def _collect_package(self, command: Command, context: _ExtractionContext) -> None:
        if len(command.words) < 2:
            return

        subcommand = word_static_text(command.words[1])
        if subcommand == 'require' and len(command.words) >= 3:
            package_name = word_static_text(command.words[2])
            if package_name is None:
                return
            if is_builtin_package(
                package_name,
                metadata_registry=self._metadata_registry,
            ):
                self._active_builtin_packages.add(canonical_builtin_package_name(package_name))
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
            arity=proc_parameter_arity(command.parameter_items),
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
        variable_word = command.words[1]
        assigned_values = (
            exact_word_values(command.words[2], context.flow_state)
            if len(command.words) >= 3
            else ()
        )
        variable_name = self._simple_variable_name(variable_word)
        if variable_name is None:
            dynamic_names = dynamic_variable_target_names(variable_word, context.flow_state)
            if not dynamic_names:
                return

            if len(command.words) >= 3:
                for name in dynamic_names:
                    self._record_variable_binding(
                        name=name,
                        span=variable_word.span,
                        context=context,
                        kind='set',
                        exact_values=assigned_values,
                    )
                    if context.procedure_symbol_id is None:
                        self._record_variable_reference(
                            name=name,
                            span=variable_word.span,
                            context=context,
                        )
                return

            for name in dynamic_names:
                self._record_variable_reference(
                    name=name,
                    span=variable_word.span,
                    context=context,
                )
            return

        if len(command.words) >= 3:
            self._record_variable_binding(
                name=variable_name,
                span=variable_word.span,
                context=context,
                kind='set',
                exact_values=assigned_values,
            )
            if context.procedure_symbol_id is None:
                self._record_variable_reference(
                    name=variable_name,
                    span=variable_word.span,
                    context=context,
                )
            return

        self._record_variable_reference(
            name=variable_name,
            span=variable_word.span,
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

    def _collect_binary(self, command: Command, context: _ExtractionContext) -> None:
        if len(command.words) < 5:
            return
        if word_static_text(command.words[1]) != 'scan':
            return
        for variable_word in command.words[4:]:
            self._record_simple_binding_word(variable_word, context, kind='scan')

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
        variable_word = command.words[2]
        variable_name = self._simple_variable_name(variable_word)
        if variable_name is not None:
            self._record_variable_reference(
                name=variable_name,
                span=variable_word.span,
                context=context,
            )
            return

        for dynamic_name in dynamic_variable_target_names(variable_word, context.flow_state):
            self._record_variable_reference(
                name=dynamic_name,
                span=variable_word.span,
                context=context,
            )

    def _collect_unset(self, command: Command, context: _ExtractionContext) -> None:
        for variable_word in unset_target_words(command):
            variable_name = self._simple_variable_name(variable_word)
            if variable_name is not None:
                self._record_variable_reference(
                    name=variable_name,
                    span=variable_word.span,
                    context=context,
                )
                continue

            for dynamic_name in dynamic_variable_target_names(variable_word, context.flow_state):
                self._record_variable_reference(
                    name=dynamic_name,
                    span=variable_word.span,
                    context=context,
                )

    def _collect_lowered_if(
        self,
        command: LoweredIfCommand,
        context: _ExtractionContext,
    ) -> None:
        remaining_context = context
        for clause in command.clauses:
            self._collect_lowered_condition(clause.condition, remaining_context)
            clause_context, remaining_context = self._if_clause_contexts(
                clause.condition,
                remaining_context,
            )
            self._collect_lowered_body(clause.body, clause_context)
        self._collect_lowered_body(command.else_body, remaining_context)

    def _collect_lowered_catch(
        self,
        command: LoweredCatchCommand,
        context: _ExtractionContext,
    ) -> None:
        self._collect_lowered_body(command.body, context)
        for variable_word in command.command.words[2:4]:
            self._record_simple_binding_word(variable_word, context, kind='catch')

    def _collect_lowered_try(
        self,
        command: LoweredTryCommand,
        context: _ExtractionContext,
    ) -> None:
        self._collect_lowered_body(command.body, context)
        for handler in command.handlers:
            if handler.binding_word is not None:
                self._record_list_binding_word(handler.binding_word, context, kind='catch')
            self._collect_lowered_body(handler.body, context)
        self._collect_lowered_body(command.finally_body, context)

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
        for branch_patterns, body in zip(
            command.branch_patterns, command.branch_bodies, strict=True
        ):
            branch_context = self._context_with_flow_state(
                context,
                switch_branch_flow_state(
                    context.flow_state,
                    value_word=command.value_word,
                    match_mode=command.match_mode,
                    nocase=command.nocase,
                    patterns=branch_patterns,
                ),
            )
            self._collect_lowered_body(body, branch_context)

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
            embedded_language=None,
            embedded_owner_name=None,
            flow_state=VariableFlowState.empty(),
        )

    def _procedure_context(self, proc_decl: ProcDecl) -> _ExtractionContext:
        return _ExtractionContext(
            uri=proc_decl.uri,
            namespace=proc_decl.namespace,
            scope_id=proc_decl.symbol_id,
            procedure_symbol_id=proc_decl.symbol_id,
            embedded_language=None,
            embedded_owner_name=None,
            flow_state=VariableFlowState.empty(),
        )

    def _updated_context_after_command(
        self,
        command: Command,
        *,
        normalized_command_name: str | None,
        context: _ExtractionContext,
    ) -> _ExtractionContext:
        if normalized_command_name == 'set':
            return self._context_with_flow_state(
                context,
                state_with_set_command(context.flow_state, command),
            )
        if normalized_command_name == 'unset':
            return self._context_with_flow_state(
                context,
                state_with_unset_command(context.flow_state, command),
            )
        return context

    def _context_with_flow_state(
        self,
        context: _ExtractionContext,
        flow_state: VariableFlowState,
    ) -> _ExtractionContext:
        if flow_state == context.flow_state:
            return context
        return _ExtractionContext(
            uri=context.uri,
            namespace=context.namespace,
            scope_id=context.scope_id,
            procedure_symbol_id=context.procedure_symbol_id,
            embedded_language=context.embedded_language,
            embedded_owner_name=context.embedded_owner_name,
            flow_state=flow_state,
        )

    def _if_clause_contexts(
        self,
        condition: LoweredCondition | None,
        context: _ExtractionContext,
    ) -> tuple[_ExtractionContext, _ExtractionContext]:
        if condition is None:
            return context, context

        true_state, false_state = condition_branch_flow_states(
            context.flow_state,
            condition.text,
        )
        return (
            self._context_with_flow_state(context, true_state),
            self._context_with_flow_state(context, false_state),
        )

    def _record_variable_reference(
        self,
        name: str,
        span: Span,
        context: _ExtractionContext,
    ) -> None:
        name = normalize_variable_name(name)
        exact_values = context.flow_state.exact_values(name)
        if self._linked_variable(context.scope_id, name) is not None:
            self._record_custom_variable_reference(
                name=name,
                span=span,
                namespace=context.namespace,
                scope_id=context.scope_id,
                procedure_symbol_id=context.procedure_symbol_id,
                uri=context.uri,
                exact_values=exact_values,
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
                exact_values=exact_values,
            )
            return

        self._record_custom_variable_reference(
            name=name,
            span=span,
            namespace=context.namespace,
            scope_id=context.scope_id,
            procedure_symbol_id=context.procedure_symbol_id,
            uri=context.uri,
            exact_values=exact_values,
        )

    def _record_variable_binding(
        self,
        name: str,
        span: Span,
        context: _ExtractionContext,
        kind: BindingKind,
        exact_values: tuple[str, ...] | None = None,
    ) -> None:
        name = normalize_variable_name(name)
        if exact_values is None:
            exact_values = context.flow_state.exact_values(name)
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
                exact_values=exact_values,
            )
            return

        direct_target = self._direct_namespace_variable_target(
            name=name,
            uri=context.uri,
            namespace=context.namespace,
        )
        if direct_target is not None:
            self._record_namespace_binding(
                target=direct_target,
                span=span,
                uri=context.uri,
                kind=kind,
                exact_values=exact_values,
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
            exact_values=exact_values,
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
        exact_values: tuple[str, ...] = (),
    ) -> None:
        self._variable_references.append(
            VariableReference(
                uri=uri,
                name=name,
                namespace=namespace,
                scope_id=scope_id,
                procedure_symbol_id=procedure_symbol_id,
                span=span,
                exact_values=exact_values,
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
        exact_values: tuple[str, ...] = (),
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
                exact_values=exact_values,
            )
        )

    def _record_namespace_binding(
        self,
        *,
        target: _VariableTarget,
        span: Span,
        uri: str,
        kind: BindingKind,
        exact_values: tuple[str, ...] = (),
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
            exact_values=exact_values,
        )

    def _simple_variable_name(self, word: Word) -> str | None:
        variable_name = _word_variable_name(word)
        if variable_name is None:
            return None
        if not is_simple_name(variable_name):
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

    def _parameter_decls_from_plugin_names(
        self,
        names: tuple[str, ...],
        *,
        source_span: Span,
        uri: str,
        proc_symbol_id: str,
    ) -> tuple[ParameterDecl, ...]:
        parameters: list[ParameterDecl] = []
        for name in names:
            if not is_simple_name(name):
                continue
            parameters.append(
                ParameterDecl(
                    symbol_id=variable_symbol_id(uri, proc_symbol_id, name),
                    name=name,
                    span=source_span,
                )
            )
        return tuple(parameters)

    def _plugin_word_texts(
        self,
        words: tuple[Word, ...],
    ) -> tuple[tuple[str, ...], tuple[bool, ...]]:
        texts: list[str] = []
        static_flags: list[bool] = []
        for word in words:
            static_text = word_static_text(word)
            texts.append(static_text or '')
            static_flags.append(static_text is not None)
        return tuple(texts), tuple(static_flags)

    def _plugin_flag_list(self, flags: tuple[bool, ...]) -> str:
        return ' '.join('1' if flag else '0' for flag in flags)

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


def _word_variable_name(word: Word) -> str | None:
    variable_name = word_static_text(word)
    if variable_name is not None:
        return normalize_variable_name(variable_name)

    if isinstance(word, BracedWord):
        return None

    saw_open_paren = False
    pieces: list[str] = []
    for part in word.parts:
        if isinstance(part, LiteralText):
            if '(' in part.text:
                saw_open_paren = True
            pieces.append(part.text)
            continue
        if not saw_open_paren:
            return None
        pieces.append('x')

    if not saw_open_paren:
        return None

    variable_name = normalize_variable_name(''.join(pieces))
    if not is_simple_name(variable_name):
        return None
    return variable_name
