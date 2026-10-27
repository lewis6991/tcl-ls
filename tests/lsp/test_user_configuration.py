import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path

import pytest

from tcl_lsp.checker import check_project
from tcl_lsp.checker import service as checker_service
from tcl_lsp.project.config import config_files
from tests.lsp_service import LanguageService
from tests.project_support import write_sample_library_root, write_sample_plugin_bundle


@pytest.mark.skipif(
    'forkserver' not in multiprocessing.get_all_start_methods(),
    reason='forkserver is not available',
)
def test_parallel_checks_use_current_user_settings_after_worker_launcher_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor_factory = partial(
        ProcessPoolExecutor, mp_context=multiprocessing.get_context('forkserver')
    )
    with executor_factory(max_workers=1) as executor:
        executor.submit(os.getpid).result()
    monkeypatch.setattr(checker_service, 'ProcessPoolExecutor', executor_factory)

    source = tmp_path / 'main.tcl'
    source.write_text('user_command\nmissing_command\n')
    home = tmp_path / 'home'
    monkeypatch.setenv('HOME', str(home))
    for config_home, severity in ((tmp_path / 'custom-config', 'hint'), (None, 'error')):
        if config_home is None:
            monkeypatch.delenv('XDG_CONFIG_HOME')
            config_home = home / '.config'
        else:
            monkeypatch.setenv('XDG_CONFIG_HOME', str(config_home))
        config = config_home / 'tcl-ls' / 'tcllsrc.tcl'
        config.parent.mkdir(parents=True)
        config.write_text(
            'meta module Tcl {meta command user_command {}}\n'
            f'diagnostic unresolved-command {severity}\n'
        )
        report = check_project(source, threads=2)
        assert [(d.diagnostic.code, d.diagnostic.severity) for d in report.diagnostics] == [
            ('unresolved-command', severity)
        ]


@pytest.mark.parametrize('xdg_home', [None, '', 'relative/config', 'absolute'])
@pytest.mark.parametrize('threads', [1, 2])
def test_user_configuration_uses_xdg_directory_or_home_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, xdg_home: str | None, threads: int
) -> None:
    home = tmp_path / 'home'
    monkeypatch.setenv('HOME', str(home))
    if xdg_home is None:
        monkeypatch.delenv('XDG_CONFIG_HOME')
    else:
        value = str(tmp_path / 'custom-config') if xdg_home == 'absolute' else xdg_home
        monkeypatch.setenv('XDG_CONFIG_HOME', value)

    fallback = home / '.config' / 'tcl-ls' / 'tcllsrc.tcl'
    fallback.parent.mkdir(parents=True)
    fallback.write_text('diagnostic unresolved-command off\n')
    config = (
        tmp_path / 'custom-config' / 'tcl-ls' / 'tcllsrc.tcl'
        if xdg_home == 'absolute'
        else fallback
    )
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        'meta module Tcl {meta command user_command {}}\ndiagnostic unresolved-command hint\n'
    )
    source = tmp_path / 'main.tcl'
    source.write_text('user_command\nmissing_command\n')

    service = LanguageService()
    try:
        diagnostics = service.open_document(source.as_uri(), source.read_text(), 1)
        assert [(d.code, d.severity) for d in diagnostics] == [('unresolved-command', 'hint')]
        report = check_project(source, threads=threads)
        assert [(d.diagnostic.code, d.diagnostic.severity) for d in report.diagnostics] == [
            ('unresolved-command', 'hint')
        ]
    finally:
        service.server.shutdown()


def test_missing_explicit_xdg_config_does_not_load_the_home_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / 'home'
    monkeypatch.setenv('HOME', str(home))
    fallback = home / '.config' / 'tcl-ls' / 'tcllsrc.tcl'
    fallback.parent.mkdir(parents=True)
    fallback.write_text('unknown-setting\n')
    source = tmp_path / 'main.tcl'
    source.write_text('puts ok\n')
    service = LanguageService()
    try:
        assert service.open_document(source.as_uri(), source.read_text(), 1) == ()
        assert check_project(source, threads=1).diagnostics == ()
    finally:
        service.server.shutdown()


@pytest.mark.parametrize('threads', [1, 2])
@pytest.mark.parametrize('selection', ['module SampleTool', 'module SampleTool when {1}'])
def test_user_configuration_shares_includes_plugins_modules_and_libraries_between_checkouts(
    tmp_path: Path, threads: int, selection: str
) -> None:
    shared = tmp_path / 'shared'
    write_sample_plugin_bundle(shared)
    metadata = shared / 'sample.meta.tcl'
    metadata.write_text(metadata.read_text().replace('meta module Tcl', 'meta module SampleTool'))
    write_sample_library_root(shared / 'libs')
    (shared / 'tcllsrc.tcl').write_text(f'source sample.meta.tcl\n{selection}\nlib-path libs\n')
    config = tmp_path / 'user-config' / 'tcl-ls' / 'tcllsrc.tcl'
    config.parent.mkdir(parents=True)
    config.write_text(f'source {{{shared / "tcllsrc.tcl"}}}\n')

    service = LanguageService()
    try:
        for name in ('checkout-one', 'checkout-two'):
            checkout = tmp_path / name
            checkout.mkdir()
            source = checkout / 'main.tcl'
            source.write_text(
                'package require samplelib\n'
                'dsl::define greet {{name}} {puts $name}\n'
                'greet world\n'
                'samplelib::greet\n'
            )
            assert service.open_document(source.as_uri(), source.read_text(), 1) == ()
            assert check_project(source, threads=threads).diagnostics == ()
            locations = service.definition(source.as_uri(), 2, 1)
            assert [(loc.uri, loc.range.start.line) for loc in locations] == [(source.as_uri(), 1)]
    finally:
        service.server.shutdown()


@pytest.mark.parametrize('threads', [1, 2])
def test_project_configuration_overrides_user_settings_in_directory_order(
    tmp_path: Path, threads: int
) -> None:
    user_config = tmp_path / 'user-config' / 'tcl-ls' / 'tcllsrc.tcl'
    user_config.parent.mkdir(parents=True)
    user_config.write_text(
        'meta module Tcl {meta command shared {user}}\ndiagnostic unresolved-command hint\n'
    )
    project = tmp_path / 'project'
    nested = project / 'nested'
    nested.mkdir(parents=True)
    (project / 'tcllsrc.tcl').write_text(
        'meta module Tcl {meta command shared {}}\ndiagnostic unresolved-command warning\n'
    )
    (nested / 'tcllsrc.tcl').write_text(
        'meta module Tcl {meta command shared {project}}\ndiagnostic unresolved-command error\n'
    )
    service = LanguageService()
    try:
        for directory, severity, argument in ((project, 'warning', ''), (nested, 'error', ' arg')):
            source = directory / 'main.tcl'
            source.write_text(f'shared{argument}\nmissing_command\n')
            diagnostics = service.open_document(source.as_uri(), source.read_text(), 1)
            assert [(d.code, d.severity) for d in diagnostics] == [('unresolved-command', severity)]
            report = check_project(source, threads=threads)
            assert [(d.diagnostic.code, d.diagnostic.severity) for d in report.diagnostics] == [
                ('unresolved-command', severity)
            ]
    finally:
        service.server.shutdown()


def test_user_configuration_is_loaded_once_and_can_be_corrected_when_invalid(
    tmp_path: Path,
) -> None:
    config = tmp_path / 'user-config' / 'tcl-ls' / 'tcllsrc.tcl'
    config.parent.mkdir(parents=True)
    config.write_text('unknown-setting\n')
    assert config_files(config.parent / 'main.tcl') == (config,)
    assert config_files(config.parent / 'main.tcl', include_user=False) == ()
    service = LanguageService()
    try:
        diagnostics = service.open_document(config.as_uri(), config.read_text(), 1)
        assert [d.code for d in diagnostics] == ['invalid-project-config']
        assert [d.diagnostic.code for d in check_project(config, threads=1).diagnostics] == [
            'invalid-project-config'
        ]
        assert service.change_document(config.as_uri(), 'lib-path libs\n', 2) == ()
    finally:
        service.server.shutdown()


def test_user_configuration_and_included_metadata_reload_on_analysis(tmp_path: Path) -> None:
    config = tmp_path / 'user-config' / 'tcl-ls' / 'tcllsrc.tcl'
    config.parent.mkdir(parents=True)
    metadata = config.parent / 'commands.meta.tcl'
    metadata.write_text('meta module Tcl {meta command shared {}}\n')
    source = tmp_path / 'main.tcl'
    source.write_text('shared\nmissing_command\n')
    service = LanguageService()
    try:
        diagnostics = service.open_document(source.as_uri(), source.read_text(), 1)
        assert [d.code for d in diagnostics] == ['unresolved-command', 'unresolved-command']
        config.write_text('source commands.meta.tcl\ndiagnostic unresolved-command hint\n')
        diagnostics = service.change_document(source.as_uri(), source.read_text(), 2)
        assert [(d.code, d.severity) for d in diagnostics] == [('unresolved-command', 'hint')]
        metadata.write_text('meta module Tcl {meta command shared {value}}\n')
        config.write_text('source commands.meta.tcl\ndiagnostic unresolved-command error\n')
        diagnostics = service.change_document(source.as_uri(), source.read_text(), 3)
        assert sorted((d.span.start.line, d.code, d.severity) for d in diagnostics) == [
            (0, 'wrong-argument-count', 'error'),
            (1, 'unresolved-command', 'error'),
        ]
        config.unlink()
        diagnostics = service.change_document(source.as_uri(), source.read_text(), 4)
        assert [d.code for d in diagnostics] == ['unresolved-command', 'unresolved-command']
    finally:
        service.server.shutdown()


def test_user_configuration_does_not_change_the_reference_search_root(tmp_path: Path) -> None:
    config = tmp_path / 'user-config' / 'tcl-ls' / 'tcllsrc.tcl'
    config.parent.mkdir(parents=True)
    config.write_text('diagnostic unresolved-command hint\n')
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'pkgIndex.tcl').write_text('')
    definition = project / 'defs.tcl'
    definition.write_text('proc greet {} {}\n')
    caller = project / 'main.tcl'
    caller.write_text(f'source {{{definition}}}\ngreet\n')
    service = LanguageService()
    try:
        service.open_document(definition.as_uri(), definition.read_text(), 1)
        locations = service.references(definition.as_uri(), 0, 6, include_declaration=False)
        assert [(loc.uri, loc.range.start.line) for loc in locations] == [(caller.as_uri(), 1)]
    finally:
        service.server.shutdown()
