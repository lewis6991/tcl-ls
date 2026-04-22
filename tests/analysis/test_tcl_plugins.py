from __future__ import annotations

from pathlib import Path

import pytest

from tcl_lsp.analysis.metadata_commands import MetadataPlugin
from tcl_lsp.plugins.host import PluginProcedureEffect, TclPluginHost


def test_tcl_plugin_host_returns_procedure_effect(tmp_path: Path) -> None:
    plugin = _plugin(
        tmp_path,
        'simple.tcl',
        'namespace eval ::test {}\n'
        'proc ::test::emit {words info} {\n'
        '    return [list [list procedure [format {\n'
        '        name select 2\n'
        '        params literal %s\n'
        '        _params-source select 3\n'
        '        body select 4\n'
        '        language sample\n'
        '    } [list {left right}]]]]\n'
        '}\n',
    )
    host = TclPluginHost()

    try:
        effects = host.call_plugin(
            plugin,
            words=('tepam::procedure', 'demo', 'attrs', 'body'),
            info={'metadata-command': 'tepam::procedure'},
        )
    finally:
        host.close()

    assert effects == (
        PluginProcedureEffect(
            name_word_index=1,
            parameter_word_index=2,
            parameter_names=('left', 'right'),
            body_word_index=3,
            body_context='sample',
        ),
    )


def test_tcl_plugin_host_returns_structured_procedure_effect(tmp_path: Path) -> None:
    plugin = _plugin(
        tmp_path,
        'structured.tcl',
        'namespace eval ::test {}\n'
        'proc ::test::emit {words info} {\n'
        '    return [list [list procedure {\n'
        '        name select 2\n'
        '        params literal {left right}\n'
        '        _params-source select 3\n'
        '        body select 4\n'
        '        language sample\n'
        '    }]]\n'
        '}\n',
    )
    host = TclPluginHost()

    try:
        effects = host.call_plugin(
            plugin,
            words=('tepam::procedure', 'demo', 'attrs', 'body'),
            info={'metadata-command': 'tepam::procedure'},
        )
    finally:
        host.close()

    assert effects == (
        PluginProcedureEffect(
            name_word_index=1,
            parameter_word_index=2,
            parameter_names=('left', 'right'),
            body_word_index=3,
            body_context='sample',
        ),
    )


def test_tcl_plugin_host_returns_declaration_effect(tmp_path: Path) -> None:
    plugin = _plugin(
        tmp_path,
        'declaration.tcl',
        'namespace eval ::test {}\n'
        'proc ::test::emit {words info} {\n'
        '    return [list [list procedure [format {\n'
        '        name select 2\n'
        '        params literal %s\n'
        '        _params-source select 3\n'
        '    } [list {left right}]]]]\n'
        '}\n',
    )
    host = TclPluginHost()

    try:
        effects = host.call_plugin(
            plugin,
            words=('dsl::declare', 'demo', 'attrs'),
            info={'metadata-command': 'dsl::declare'},
        )
    finally:
        host.close()

    assert effects == (
        PluginProcedureEffect(
            name_word_index=1,
            parameter_word_index=2,
            parameter_names=('left', 'right'),
            body_word_index=None,
            body_context=None,
        ),
    )


def test_tcl_plugin_host_blocks_channel_io(tmp_path: Path) -> None:
    plugin = _plugin(
        tmp_path,
        'puts.tcl',
        'namespace eval ::test {}\nproc ::test::emit {words info} {\n    puts stdout blocked\n}\n',
    )
    host = TclPluginHost()

    try:
        with pytest.raises(RuntimeError, match='invalid command name "puts"'):
            host.call_plugin(plugin, words=('demo',), info={})
    finally:
        host.close()


def test_tcl_plugin_host_blocks_package_loading(tmp_path: Path) -> None:
    plugin = _plugin(
        tmp_path,
        'package.tcl',
        'namespace eval ::test {}\n'
        'proc ::test::emit {words info} {\n'
        '    package require TclOO\n'
        '}\n',
    )
    host = TclPluginHost()

    try:
        with pytest.raises(RuntimeError, match='invalid command name "package"'):
            host.call_plugin(plugin, words=('demo',), info={})
    finally:
        host.close()


def test_tcl_plugin_host_resets_state_between_calls(tmp_path: Path) -> None:
    plugin = _plugin(
        tmp_path,
        'state.tcl',
        'namespace eval ::test {\n'
        '    variable count 0\n'
        '}\n'
        'proc ::test::emit {words info} {\n'
        '    variable ::test::count\n'
        '    incr count\n'
        '    return [list [list procedure [format {\n'
        '        name select 2\n'
        '        params literal %s\n'
        '        _params-source select 3\n'
        '        body select 4\n'
        '    } [list [list $count]]]]]\n'
        '}\n',
    )
    host = TclPluginHost()

    try:
        first_effects = host.call_plugin(plugin, words=('demo', 'name', 'args', 'body'), info={})
        second_effects = host.call_plugin(plugin, words=('demo', 'name', 'args', 'body'), info={})
    finally:
        host.close()

    expected_effect = PluginProcedureEffect(
        name_word_index=1,
        parameter_word_index=2,
        parameter_names=('1',),
        body_word_index=3,
        body_context=None,
    )
    assert first_effects == (expected_effect,)
    assert second_effects == (expected_effect,)


def _plugin(tmp_path: Path, file_name: str, script: str) -> MetadataPlugin:
    script_path = tmp_path / file_name
    script_path.write_text(script, encoding='utf-8')
    return MetadataPlugin(script_path=script_path, proc_name='::test::emit')
