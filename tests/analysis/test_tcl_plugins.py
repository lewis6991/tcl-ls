from __future__ import annotations

from pathlib import Path

import pytest

from tcl_lsp.analysis.metadata_commands import (
    MetadataBind,
    MetadataContext,
    MetadataPackage,
    MetadataPlugin,
    MetadataProcedure,
    MetadataRef,
    MetadataSelector,
    MetadataSource,
)
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
            procedure=MetadataProcedure(
                member_name_selector=_selector(2),
                member_name_literal=None,
                parameter_selector=None,
                parameter_literal='left right',
                body_selector=_selector(4),
                body_context='sample',
            ),
            parameter_source_selector=_selector(3),
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
            procedure=MetadataProcedure(
                member_name_selector=_selector(2),
                member_name_literal=None,
                parameter_selector=None,
                parameter_literal='left right',
                body_selector=_selector(4),
                body_context='sample',
            ),
            parameter_source_selector=_selector(3),
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
            procedure=MetadataProcedure(
                member_name_selector=_selector(2),
                member_name_literal=None,
                parameter_selector=None,
                parameter_literal='left right',
                body_selector=None,
                body_context=None,
            ),
            parameter_source_selector=_selector(3),
        ),
    )


def test_tcl_plugin_host_returns_dynamic_clause_effects(tmp_path: Path) -> None:
    plugin = _plugin(
        tmp_path,
        'dynamic.tcl',
        'namespace eval ::test {}\n'
        'proc ::test::emit {words info} {\n'
        '    return [list \\\n'
        '        [list bind 2 set] \\\n'
        '        [list ref list 3] \\\n'
        '        [list package literal TclOO] \\\n'
        '        [list package select 3] \\\n'
        '        [list source 4 caller] \\\n'
        '        [list enter sample body 5 owner 2] \\\n'
        '    ]\n'
        '}\n',
    )
    host = TclPluginHost()

    try:
        effects = host.call_plugin(
            plugin,
            words=('dsl::run', 'ownerName', 'pkgName', 'helper.tcl', 'body'),
            info={'metadata-command': 'dsl::run'},
        )
    finally:
        host.close()

    assert effects == (
        MetadataBind(selector=_selector(2), kind='set'),
        MetadataRef(selector=MetadataSelector(2, False, True, False)),
        MetadataPackage(selector=None, literal_package='TclOO'),
        MetadataPackage(selector=_selector(3), literal_package=None),
        MetadataSource(selector=_selector(4), base='caller'),
        MetadataContext(
            body_selector=_selector(5),
            context_name='sample',
            owner_selector=_selector(2),
        ),
    )


def test_tcl_plugin_host_rejects_static_declarations_in_effects(tmp_path: Path) -> None:
    plugin = _plugin(
        tmp_path,
        'invalid.tcl',
        'namespace eval ::test {}\n'
        'proc ::test::emit {words info} {\n'
        '    return [list [list command child {x}]]\n'
        '}\n',
    )
    host = TclPluginHost()

    try:
        with pytest.raises(RuntimeError, match='Unknown Tcl plugin effect `command`'):
            host.call_plugin(plugin, words=('demo',), info={})
    finally:
        host.close()


def test_tcl_plugin_host_rejects_after_options_selectors(tmp_path: Path) -> None:
    plugin = _plugin(
        tmp_path,
        'after_options.tcl',
        'namespace eval ::test {}\n'
        'proc ::test::emit {words info} {\n'
        '    return [list [list package select after-options 2]]\n'
        '}\n',
    )
    host = TclPluginHost()

    try:
        with pytest.raises(RuntimeError, match='does not support `after-options`'):
            host.call_plugin(plugin, words=('demo',), info={})
    finally:
        host.close()


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
        procedure=MetadataProcedure(
            member_name_selector=_selector(2),
            member_name_literal=None,
            parameter_selector=None,
            parameter_literal='1',
            body_selector=_selector(4),
            body_context=None,
        ),
        parameter_source_selector=_selector(3),
    )
    assert first_effects == (expected_effect,)
    assert second_effects == (expected_effect,)


def _plugin(tmp_path: Path, file_name: str, script: str) -> MetadataPlugin:
    script_path = tmp_path / file_name
    script_path.write_text(script, encoding='utf-8')
    return MetadataPlugin(script_path=script_path, proc_name='::test::emit')


def _selector(index: int) -> MetadataSelector:
    return MetadataSelector(
        start_index=index - 1,
        all_remaining=False,
        list_mode=False,
        after_options=False,
    )
