from pathlib import Path

import pytest

from tcl_lsp.checker import check_project
from tcl_lsp.lsp import LanguageServer
from tcl_lsp.lsp.features.completion import completion_items
from tcl_lsp.lsp.features.hover import hover
from tcl_lsp.lsp.features.navigation import definition, references
from tcl_lsp.lsp.semantic_tokens import (
    SEMANTIC_TOKEN_MODIFIERS,
    SEMANTIC_TOKEN_TYPES,
    encode_document_semantic_tokens,
)
from tests.lsp.helpers import decode_semantic_tokens


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / 'tcllsrc.tcl').write_text(
        'meta module Tcl {\n'
        '    meta command app::dispatch {command args} {call 1.. namespace ::}\n'
        '    meta command app::local_dispatch {command args} {call 1..}\n'
        '    meta command app::scoped_dispatch {command args} {call 1.. namespace ::service::}\n'
        '    meta command app::internal_dispatch {code command args} {call 2.. namespace ::}\n'
        '}\n'
        'meta module Runtime {\n'
        '    # Check one value in the runtime.\n'
        '    meta command runtime_check {value}\n'
        '    meta command service::runtime_check {first second}\n'
        '}\n'
        'module Runtime\n'
    )
    return tmp_path


def test_forwarded_command_has_editor_features_and_root_namespace_lookup(project: Path) -> None:
    source = project / 'main.tcl'
    text = (
        'namespace eval app {\n'
        '    proc runtime_check {first second} {list $first $second}\n'
        '    proc run {value} {\n'
        '        dispatch runtime_check $value\n'
        '        local_dispatch runtime_check first second\n'
        '    }\n'
        '}\n'
    )
    source.write_text(text)
    server = LanguageServer()
    try:
        assert server.open_document(source.as_uri(), text, 1) == ()
        assert check_project(source, threads=1).diagnostics == ()
        uri = source.as_uri()
        line = text.splitlines()[3]
        column = line.index('runtime_check') + 2
        info = hover(server.documents, uri=uri, line=3, character=column)
        assert info is not None
        assert 'Check one value in the runtime.' in info.contents
        snapshot = server.analysis_snapshot()
        locations = definition(
            snapshot.documents,
            workspace_index=snapshot.workspace_index,
            metadata_registry=snapshot.metadata_registry,
            uri=uri,
            line=3,
            character=column,
        )
        assert len(locations) == 1
        assert locations[0].uri == (project / 'tcllsrc.tcl').as_uri()
        uses = references(
            snapshot.documents,
            metadata_registry=snapshot.metadata_registry,
            uri=uri,
            line=3,
            character=column,
            include_declaration=False,
        )
        assert [(location.uri, location.range.start.line) for location in uses] == [(uri, 3)]
        signature = server.signature_help_at(
            snapshot, uri=uri, line=3, character=line.index('$value')
        )
        assert signature is not None
        assert signature.signatures[0].label == 'runtime_check {value}'
        items = completion_items(
            snapshot.documents,
            workspace_index=snapshot.workspace_index,
            metadata_registry=snapshot.metadata_registry,
            uri=uri,
            line=3,
            character=column,
        )
        assert 'runtime_check' in {item.label for item in items.items}
        document = server.documents[uri]
        encoded = encode_document_semantic_tokens(
            text=text, facts=document.facts, analysis=document.analysis
        )
        tokens = decode_semantic_tokens(
            list(encoded),
            token_types=list(SEMANTIC_TOKEN_TYPES),
            token_modifiers=list(SEMANTIC_TOKEN_MODIFIERS),
        )
        positions = {(index, text.splitlines()[index].index('runtime_check')) for index in (3, 4)}
        target_tokens = [
            token for token in tokens if (token['line'], token['character']) in positions
        ]
        assert [(token['type'], token['modifiers']) for token in target_tokens] == [
            ('function', ['defaultLibrary']),
            ('function', []),
        ]
        variables = server.documents[uri].facts.variable_references
        assert sum(reference.name == 'value' for reference in variables) == 1
    finally:
        server.shutdown()


@pytest.mark.parametrize(
    ('call', 'expected'),
    [
        ('dispatch runtime_check {two words}', []),
        ('dispatch {runtime_check} {two words}', []),
        ('dispatch "runtime_check" {two words}', []),
        ('internal_dispatch FAILURE runtime_check {two words}', []),
        ('scoped_dispatch runtime_check first second', []),
        ('dispatch runtime_check', ['wrong-argument-count']),
        ('dispatch runtime_check first second', ['wrong-argument-count']),
        ('dispatch missing_command value', ['unresolved-command']),
        ('dispatch {runtime_check value}', ['unresolved-command']),
        ('dispatch $command value', []),
        ('dispatch {*}$command', []),
    ],
)
def test_forwarded_calls_preserve_words_and_check_the_target(
    project: Path, call: str, expected: list[str]
) -> None:
    source = project / 'main.tcl'
    text = f'namespace eval app {{proc run {{command}} {{list $command; {call}}}}}\n'
    source.write_text(text)
    server = LanguageServer()
    try:
        diagnostics = server.open_document(source.as_uri(), text, 1)
        assert [diagnostic.code for diagnostic in diagnostics] == expected
        report = check_project(source, threads=1)
        assert [item.diagnostic.code for item in report.diagnostics] == expected
    finally:
        server.shutdown()


def test_plugin_can_describe_a_forwarded_call(project: Path) -> None:
    plugin = project / 'forward.tcl'
    plugin.write_text('proc describe {words info} {return {{call 2.. namespace ::}}}\n')
    config = project / 'tcllsrc.tcl'
    with config.open('a') as stream:
        stream.write(
            'meta module Tcl {meta command plugin_dispatch {command args} '
            '{plugin forward.tcl describe}}\n'
        )
    source = project / 'main.tcl'
    text = 'plugin_dispatch runtime_check value\n'
    source.write_text(text)
    server = LanguageServer()
    try:
        assert server.open_document(source.as_uri(), text, 1) == ()
        info = hover(server.documents, uri=source.as_uri(), line=0, character=18)
        assert info is not None
        assert 'Check one value in the runtime.' in info.contents
    finally:
        server.shutdown()


@pytest.mark.parametrize(
    'annotation',
    [
        'call list 1',
        'call 1..4 step 2',
        'call 1.. namespace relative',
        'call 1.. namespace {::two words}',
        'call 1.. namespace',
        'call 1.. unexpected ::',
    ],
)
def test_invalid_call_annotations_report_a_config_error(tmp_path: Path, annotation: str) -> None:
    config = tmp_path / 'tcllsrc.tcl'
    text = f'meta module Tcl {{meta command dispatch {{args}} {{{annotation}}}}}\n'
    config.write_text(text)
    server = LanguageServer()
    try:
        diagnostics = server.open_document(config.as_uri(), text, 1)
        assert [diagnostic.code for diagnostic in diagnostics] == ['invalid-project-config']
    finally:
        server.shutdown()
