from __future__ import annotations

from collections.abc import Iterator
from importlib import import_module
from pathlib import Path

import pytest
from lsprotocol import types

from tcl_lsp.checker import check_project
from tcl_lsp.lsp import LanguageServer
from tcl_lsp.project.paths import discover_tcl_sources
from tests.lsp_support import wait_for_project_diagnostics


def test_project_scan_excludes_venv_and_keeps_callers_under_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / 'tcllsrc.tcl'
    config.write_text('exclude .venv\n')
    backend = tmp_path / 'backend.tcl'
    text = 'proc _used {} {}\nproc _unused {} {}\n'
    backend.write_text(text)
    caller = tmp_path / 'tests' / 'caller.tcl'
    caller.parent.mkdir()
    caller.write_text('_used\n')
    ignored = tmp_path / '.venv' / 'caller.tcl'
    ignored.parent.mkdir()
    ignored.write_text('_unused\n')
    # The excluded tree must not even be entered to load its settings.
    ignored_config = ignored.parent / 'tcllsrc.tcl'
    ignored_config.write_text('invalid_config\n')
    paths = import_module('tcl_lsp.project.paths')
    walk = paths.walk
    visited: list[Path] = []

    def record_walk(path: Path) -> Iterator[tuple[str, list[str], list[str]]]:
        for entry in walk(path):
            visited.append(Path(entry[0]))
            yield entry

    monkeypatch.setattr(paths, 'walk', record_walk)
    server = LanguageServer()
    try:
        server.open_document(backend.as_uri(), text, 1)
        wait_for_project_diagnostics(server)
        assert [d.message for d in server.documents[backend.as_uri()].analysis.diagnostics] == [
            'Procedure `::_unused` is unused.'
        ]
        snapshot = server.references_snapshot(backend.as_uri(), types.Position(0, 7))
        assert caller.as_uri() in snapshot.documents
        assert ignored.as_uri() not in snapshot.documents
        assert ignored.parent not in visited

        ignored_config.write_text('')
        config.write_text('')
        server.change_document(backend.as_uri(), '\n' + text, 2)
        wait_for_project_diagnostics(server)
        assert server.documents[backend.as_uri()].analysis.diagnostics == ()

        config.write_text('exclude .venv\n')
        server.change_document(backend.as_uri(), '\n\n' + text, 3)
        wait_for_project_diagnostics(server)
        assert [d.message for d in server.documents[backend.as_uri()].analysis.diagnostics] == [
            'Procedure `::_unused` is unused.'
        ]
    finally:
        server.shutdown()


def test_excluded_package_indexes_are_not_used_by_editor_or_checker(tmp_path: Path) -> None:
    (tmp_path / 'tcllsrc.tcl').write_text('exclude .venv\n')
    source = tmp_path / 'main.tcl'
    source.write_text('package require Hidden\n')
    package = tmp_path / '.venv' / 'hidden'
    package.mkdir(parents=True)
    (package / 'pkgIndex.tcl').write_text(
        'package ifneeded Hidden 1.0 [list source [file join $dir hidden.tcl]]\n'
    )
    (package / 'hidden.tcl').write_text('package provide Hidden 1.0\n')
    server = LanguageServer()
    try:
        diagnostics = server.open_document(source.as_uri(), source.read_text(), 1)
        assert [d.code for d in diagnostics] == ['unresolved-package']
        report = check_project(tmp_path, threads=1)
        assert report.source_count == 2
        assert [(d.path, d.diagnostic.code) for d in report.diagnostics] == [
            (source.resolve(), 'unresolved-package')
        ]
    finally:
        server.shutdown()


def test_excluded_files_can_be_opened_checked_and_sourced_explicitly(tmp_path: Path) -> None:
    ignored = tmp_path / '.venv'
    ignored.mkdir()
    (ignored / 'pkgIndex.tcl').write_text('package ifneeded Hidden 1.0 {}\n')
    (ignored / 'tools.meta.tcl').write_text('meta module Tcl {meta command tool {}}\n')
    (tmp_path / 'tcllsrc.tcl').write_text('exclude .venv\nsource .venv/tools.meta.tcl\n')
    helper = ignored / 'helper.tcl'
    helper.write_text('proc helper {} {tool}\n')
    source = tmp_path / 'main.tcl'
    source.write_text('source [file join [file dirname [info script]] .venv helper.tcl]\nhelper\n')
    server = LanguageServer()
    try:
        assert server.open_document(source.as_uri(), source.read_text(), 1) == ()
        assert server.open_document(helper.as_uri(), helper.read_text(), 1) == ()
        assert check_project(helper, threads=1).diagnostics == ()
        report = check_project(source, threads=1)
        assert report.diagnostics == ()
        assert report.background_source_count == 1
    finally:
        server.shutdown()


def test_parent_child_and_sourced_exclusions_keep_their_declaring_directory(tmp_path: Path) -> None:
    settings = tmp_path / 'settings'
    settings.mkdir()
    included_config = settings / 'paths.tcl'
    included_config.write_text('exclude ../generated\n')
    (tmp_path / 'tcllsrc.tcl').write_text(
        'exclude .venv\nexclude ignored.tcl\nsource settings/paths.tcl\n'
    )
    child = tmp_path / 'child'
    child.mkdir()
    (child / 'tcllsrc.tcl').write_text('exclude cache\n')
    ignored = ['.venv/bad.tcl', 'generated/bad.tcl', 'child/cache/bad.tcl', 'ignored.tcl']
    kept = ['main.tcl', '.venv-old/keep.tcl', 'child/main.tcl', 'child/generated/keep.tcl']
    for name in ignored + kept:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('puts ok\n')

    discovered = set(discover_tcl_sources(tmp_path))
    assert all(tmp_path / name not in discovered for name in ignored)
    assert all(tmp_path / name in discovered for name in kept)
    assert child / 'tcllsrc.tcl' in discovered

    included_config.write_text('exclude ../obsolete\n')
    assert tmp_path / 'generated/bad.tcl' in discover_tcl_sources(tmp_path)


@pytest.mark.parametrize('declaration', ['exclude', 'exclude one two', 'exclude {}'])
def test_invalid_exclusions_have_a_config_diagnostic(tmp_path: Path, declaration: str) -> None:
    config = tmp_path / 'tcllsrc.tcl'
    config.write_text(declaration + '\n')
    server = LanguageServer()
    try:
        diagnostics = server.open_document(config.as_uri(), config.read_text(), 1)
        assert [d.code for d in diagnostics] == ['invalid-project-config']
        report = check_project(config, threads=1)
        assert [d.diagnostic.code for d in report.diagnostics] == ['invalid-project-config']
    finally:
        server.shutdown()
