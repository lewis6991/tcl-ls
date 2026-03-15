from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from tcl_lsp.check import check_project, format_report, main


def test_check_project_resolves_cross_file_procedures(tmp_path: Path) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    (project_root / 'defs.tcl').write_text(
        'proc greet {name} {puts $name}\n',
        encoding='utf-8',
    )
    (project_root / 'use.tcl').write_text(
        'greet World\nmissing_command\n',
        encoding='utf-8',
    )

    report = check_project(project_root)

    assert report.source_count == 2
    assert [item.diagnostic.code for item in report.diagnostics] == ['unresolved-command']
    assert report.diagnostics[0].path == (project_root / 'use.tcl').resolve(strict=False)


def test_check_project_uses_pkgindex_metadata(tmp_path: Path) -> None:
    modules_root = tmp_path / 'workspace' / 'modules'
    helper_dir = modules_root / 'helper'
    app_dir = modules_root / 'app'
    helper_dir.mkdir(parents=True)
    app_dir.mkdir()

    (helper_dir / 'pkgIndex.tcl').write_text(
        'package ifneeded helper 1.0 [list source [file join $dir helper.tcl]]\n',
        encoding='utf-8',
    )
    (helper_dir / 'helper.tcl').write_text(
        'package provide helper 1.0\nproc helper::greet {} {return ok}\n',
        encoding='utf-8',
    )
    (app_dir / 'main.tcl').write_text(
        'package require helper\nhelper::greet\n',
        encoding='utf-8',
    )

    report = check_project(modules_root)

    assert report.source_count == 3
    assert report.diagnostics == ()


def test_check_project_treats_each_pkgindex_directory_as_a_workspace(tmp_path: Path) -> None:
    modules_root = tmp_path / 'workspace' / 'modules'
    first_dir = modules_root / 'first'
    second_dir = modules_root / 'second'
    first_dir.mkdir(parents=True)
    second_dir.mkdir()

    (first_dir / 'pkgIndex.tcl').write_text(
        'package ifneeded first 1.0 [list source [file join $dir first.tcl]]\n',
        encoding='utf-8',
    )
    (first_dir / 'first.tcl').write_text(
        'package provide first 1.0\nproc helper {} {return ok}\n',
        encoding='utf-8',
    )
    (second_dir / 'pkgIndex.tcl').write_text(
        'package ifneeded second 1.0 [list source [file join $dir second.tcl]]\n',
        encoding='utf-8',
    )
    (second_dir / 'second.tcl').write_text(
        'package provide second 1.0\nhelper\n',
        encoding='utf-8',
    )

    report = check_project(modules_root)

    assert [item.diagnostic.code for item in report.diagnostics] == ['unresolved-command']
    assert report.diagnostics[0].path == (second_dir / 'second.tcl').resolve(strict=False)


def test_tcl_check_main_formats_report_and_can_fail_on_diagnostics(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    (project_root / 'broken.tcl').write_text('missing_command\n', encoding='utf-8')

    exit_code = main([str(project_root), '--color=never'])
    output = capsys.readouterr()

    assert exit_code == 0
    assert output.err == ''
    output_lines = output.out.splitlines()
    assert output_lines[:5] == [
        'broken.tcl (1 diagnostic)',
        '  1:1  warning  unresolved-command  Unresolved command `missing_command`.',
        '    1 | missing_command',
        '      | ^^^^^^^^^^^^^^^',
        '',
    ]
    assert output_lines[5] == 'Summary'
    assert output_lines[6].startswith(
        f'Scanned 1 Tcl file under {project_root.resolve(strict=False)} in '
    )
    assert output_lines[7] == 'Found 1 diagnostic in 1 file.'
    assert output_lines[8] == '  unresolved-command 1'

    exit_code = main([str(project_root), '--fail-on-diagnostics', '--color=never'])
    capsys.readouterr()

    assert exit_code == 1


def test_format_report_can_include_surrounding_context(tmp_path: Path) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    (project_root / 'broken.tcl').write_text(
        'set before 1\nmissing_command\nset after 2\n',
        encoding='utf-8',
    )

    report = check_project(project_root)
    formatted = format_report(report, color=False, context_lines=1)

    assert 'broken.tcl (1 diagnostic)' in formatted
    assert '    1 | set before 1' in formatted
    assert '    2 | missing_command' in formatted
    assert '      | ^^^^^^^^^^^^^^^' in formatted
    assert '    3 | set after 2' in formatted
    assert '\nSummary\n' in formatted


def test_tcl_check_main_can_force_color_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    (project_root / 'broken.tcl').write_text('missing_command\n', encoding='utf-8')

    exit_code = main([str(project_root), '--color=always'])
    output = capsys.readouterr()

    assert exit_code == 0
    assert '\x1b[' in output.out


def test_tcl_check_main_reports_workspace_progress_on_tty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    (project_root / 'broken.tcl').write_text('missing_command\n', encoding='utf-8')

    class _FakeTty(io.StringIO):
        def isatty(self) -> bool:
            return True

    stdout = _FakeTty()
    stderr = _FakeTty()
    monkeypatch.setattr(sys, 'stdout', stdout)
    monkeypatch.setattr(sys, 'stderr', stderr)

    exit_code = main([str(project_root), '--color=never'])

    output = stdout.getvalue()
    assert exit_code == 0
    assert 'broken.tcl (1 diagnostic)\n' in output
    assert 'Summary\n' in output
    assert '[provisional]' not in output
    assert 'Preparing workspace' in stderr.getvalue()
