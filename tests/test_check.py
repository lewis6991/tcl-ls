from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from tcl_lsp.check import check_project, format_report, main


def _write_sample_plugin_bundle(metadata_root: Path) -> Path:
    metadata_root.mkdir(parents=True, exist_ok=True)
    plugin_path = metadata_root / 'sample.tm'
    plugin_path.write_text(
        'namespace eval ::tcl_lsp::plugins::sample {}\n'
        'proc ::tcl_lsp::plugins::sample::procedure {words info} {\n'
        '    if {[llength $words] < 4} {\n'
        '        return {}\n'
        '    }\n'
        '    return [list [list procedure [dict create \\\n'
        '        name-index 1 \\\n'
        '        params-word-index 2 \\\n'
        '        params [::tcl_lsp::plugins::sample::parameterNames [lindex $words 2]] \\\n'
        '        body-index 3 \\\n'
        '    ]]]\n'
        '}\n'
        'proc ::tcl_lsp::plugins::sample::parameterNames {parameter_list} {\n'
        '    set names {}\n'
        '    if {[catch {\n'
        '        foreach arg_def $parameter_list {\n'
        '            set name [lindex $arg_def 0]\n'
        '            if {$name eq ""} {\n'
        '                continue\n'
        '            }\n'
        '            lappend names $name\n'
        '        }\n'
        '    }]} {\n'
        '        return {}\n'
        '    }\n'
        '    return $names\n'
        '}\n',
        encoding='utf-8',
    )
    (metadata_root / 'sample.tcl').write_text(
        '# Project metadata loaded from project-local plugin configuration.\n'
        'meta module Tcl\n'
        '# Define a procedure using a project-local wrapper command.\n'
        'meta command dsl::define {name params body} {\n'
        '    plugin sample.tm ::tcl_lsp::plugins::sample::procedure\n'
        '}\n',
        encoding='utf-8',
    )
    return plugin_path


def _write_declaration_plugin_bundle(metadata_root: Path) -> Path:
    metadata_root.mkdir(parents=True, exist_ok=True)
    plugin_path = metadata_root / 'declaration.tm'
    plugin_path.write_text(
        'namespace eval ::tcl_lsp::plugins::sample {}\n'
        'proc ::tcl_lsp::plugins::sample::declaration {words info} {\n'
        '    if {[llength $words] < 3} {\n'
        '        return {}\n'
        '    }\n'
        '    return [list [list procedure [dict create \\\n'
        '        name-index 1 \\\n'
        '        params-word-index 2 \\\n'
        '        params [::tcl_lsp::plugins::sample::parameterNames [lindex $words 2]] \\\n'
        '    ]]]\n'
        '}\n'
        'proc ::tcl_lsp::plugins::sample::parameterNames {parameter_list} {\n'
        '    set names {}\n'
        '    if {[catch {\n'
        '        foreach arg_def $parameter_list {\n'
        '            set name [lindex $arg_def 0]\n'
        '            if {$name eq ""} {\n'
        '                continue\n'
        '            }\n'
        '            lappend names $name\n'
        '        }\n'
        '    }]} {\n'
        '        return {}\n'
        '    }\n'
        '    return $names\n'
        '}\n',
        encoding='utf-8',
    )
    (metadata_root / 'declaration.tcl').write_text(
        '# Project metadata loaded from project-local plugin configuration.\n'
        'meta module Tcl\n'
        '# Declare a procedure using a project-local wrapper command.\n'
        'meta command dsl::declare {name params} {\n'
        '    plugin declaration.tm ::tcl_lsp::plugins::sample::declaration\n'
        '}\n',
        encoding='utf-8',
    )
    return plugin_path


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

    report = check_project(app_dir / 'main.tcl')

    assert report.source_count == 1
    assert report.background_source_count == 1
    assert report.diagnostics == ()


def test_check_project_loads_static_source_commands(tmp_path: Path) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    (project_root / 'helper.inc').write_text(
        'proc greet {} {return ok}\n',
        encoding='utf-8',
    )
    (project_root / 'main.tcl').write_text(
        'source [file join [file dirname [info script]] helper.inc]\ngreet\n',
        encoding='utf-8',
    )

    report = check_project(project_root)

    assert report.source_count == 1
    assert report.background_source_count == 1
    assert report.diagnostics == ()


def test_check_project_uses_helper_metadata_for_embedded_dependencies(tmp_path: Path) -> None:
    project_root = tmp_path / 'workspace'
    devtools_root = project_root / 'devtools'
    package_root = project_root / 'pkg'
    devtools_root.mkdir(parents=True)
    package_root.mkdir()

    (devtools_root / 'testutilities.tcl').write_text(
        'proc testing {script} {}\n'
        'proc useLocal {fname pname args} {}\n'
        'proc testsNeed {name {version {}}} {}\n',
        encoding='utf-8',
    )
    (package_root / 'helper.tcl').write_text(
        'proc helper {} {return ok}\n',
        encoding='utf-8',
    )
    (package_root / 'main.test').write_text(
        'source [file join [file dirname [file dirname [info script]]] devtools testutilities.tcl]\n'
        'testing {\n'
        '    useLocal helper.tcl demo\n'
        '    testsNeed Tk 8.5\n'
        '}\n'
        'helper\n'
        'frame .f\n',
        encoding='utf-8',
    )

    report = check_project(package_root / 'main.test')

    assert report.source_count == 1
    assert report.background_source_count == 2
    assert report.diagnostics == ()


def test_check_project_uses_helper_metadata_for_proc_source_parent_loads(tmp_path: Path) -> None:
    project_root = tmp_path / 'workspace'
    devtools_root = project_root / 'devtools'
    package_root = project_root / 'pkg'
    shared_root = project_root / 'shared'
    devtools_root.mkdir(parents=True)
    package_root.mkdir()
    shared_root.mkdir()

    (devtools_root / 'testutilities.tcl').write_text(
        'proc testing {script} {}\nproc use {fname pname args} {}\n',
        encoding='utf-8',
    )
    (shared_root / 'helper.tcl').write_text(
        'proc helper {} {return ok}\n',
        encoding='utf-8',
    )
    (package_root / 'main.test').write_text(
        'source [file join [file dirname [file dirname [info script]]] devtools testutilities.tcl]\n'
        'testing {\n'
        '    use shared/helper.tcl demo\n'
        '}\n'
        'helper\n',
        encoding='utf-8',
    )

    report = check_project(package_root / 'main.test')

    assert report.source_count == 1
    assert report.background_source_count == 2
    assert report.diagnostics == ()


def test_check_project_does_not_apply_helper_metadata_to_other_sources(tmp_path: Path) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    (project_root / 'helpers.tcl').write_text(
        'proc useLocal {fname pname args} {}\n',
        encoding='utf-8',
    )
    (project_root / 'helper.tcl').write_text(
        'proc helper {} {return ok}\n',
        encoding='utf-8',
    )
    (project_root / 'main.tcl').write_text(
        'source [file join [file dirname [info script]] helpers.tcl]\n'
        'useLocal helper.tcl demo\n'
        'helper\n',
        encoding='utf-8',
    )

    report = check_project(project_root / 'main.tcl')

    assert [item.diagnostic.code for item in report.diagnostics] == ['unresolved-command']
    assert report.diagnostics[0].diagnostic.message == 'Unresolved command `helper`.'


def test_check_project_loads_transitive_static_source_commands(tmp_path: Path) -> None:
    package_root = tmp_path / 'workspace' / 'modules' / 'demo'
    package_root.mkdir(parents=True)
    (package_root / 'support.inc').write_text(
        'source [file join [file dirname [info script]] helper.inc]\n',
        encoding='utf-8',
    )
    (package_root / 'helper.inc').write_text(
        'proc greet {} {return ok}\n',
        encoding='utf-8',
    )
    (package_root / 'main.test').write_text(
        'source [file join [file dirname [file dirname [file join [pwd] [info script]]]] demo support.inc]\n'
        'greet\n',
        encoding='utf-8',
    )

    report = check_project(package_root)

    assert report.source_count == 1
    assert report.background_source_count == 2
    assert report.diagnostics == ()


def test_check_project_loads_external_plugin_metadata_from_plugin_path(tmp_path: Path) -> None:
    metadata_root = tmp_path / 'metadata'
    plugin_path = _write_sample_plugin_bundle(metadata_root)

    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    (project_root / 'main.tcl').write_text(
        'dsl::define greet {{name}} {puts $name}\ngreet World\n',
        encoding='utf-8',
    )

    baseline_report = check_project(project_root)
    plugin_report = check_project(project_root, threads=2, plugin_paths=(plugin_path,))
    restored_report = check_project(project_root)

    assert [item.diagnostic.code for item in baseline_report.diagnostics] == [
        'unresolved-command',
        'unresolved-command',
    ]
    assert plugin_report.diagnostics == ()
    assert [item.diagnostic.code for item in restored_report.diagnostics] == [
        'unresolved-command',
        'unresolved-command',
    ]


def test_check_project_loads_external_declaration_plugin_metadata(tmp_path: Path) -> None:
    metadata_root = tmp_path / 'metadata'
    plugin_path = _write_declaration_plugin_bundle(metadata_root)

    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    (project_root / 'main.tcl').write_text(
        'dsl::declare greet {{name}}\ngreet World\n',
        encoding='utf-8',
    )

    baseline_report = check_project(project_root)
    plugin_report = check_project(project_root, threads=2, plugin_paths=(plugin_path,))

    assert [item.diagnostic.code for item in baseline_report.diagnostics] == [
        'unresolved-command',
        'unresolved-command',
    ]
    assert plugin_report.diagnostics == ()


def test_check_project_loads_plugin_metadata_from_tcllsrc(tmp_path: Path) -> None:
    project_root = tmp_path / 'workspace'
    package_root = project_root / 'pkg'
    plugin_path = _write_sample_plugin_bundle(project_root / '.tcl-ls')
    package_root.mkdir(parents=True)

    (project_root / 'tcllsrc.tcl').write_text(
        'plugin-path .tcl-ls/sample.tm\n',
        encoding='utf-8',
    )
    (package_root / 'main.tcl').write_text(
        'dsl::define greet {{name}} {puts $name}\ngreet World\n',
        encoding='utf-8',
    )

    report = check_project(package_root)

    assert plugin_path.is_file()
    assert report.diagnostics == ()


def test_check_project_loads_generated_project_metadata_without_docs(tmp_path: Path) -> None:
    project_root = tmp_path / 'workspace'
    package_root = project_root / 'pkg'
    _write_sample_plugin_bundle(project_root / '.tcl-ls')
    (project_root / '.tcl-ls' / 'generated.tcl').write_text(
        'meta module Tcl\nmeta command external {args}\n',
        encoding='utf-8',
    )
    package_root.mkdir(parents=True)

    (project_root / 'tcllsrc.tcl').write_text(
        'plugin-path .tcl-ls/sample.tm\n',
        encoding='utf-8',
    )
    (package_root / 'main.tcl').write_text(
        'external run\n',
        encoding='utf-8',
    )

    report = check_project(package_root)

    assert report.diagnostics == ()


def test_check_project_restores_project_metadata_between_calls(tmp_path: Path) -> None:
    project_with_plugin = tmp_path / 'with-plugin'
    project_without_plugin = tmp_path / 'without-plugin'
    _write_sample_plugin_bundle(project_with_plugin / '.tcl-ls')
    (project_with_plugin / 'tcllsrc.tcl').write_text(
        'plugin-path .tcl-ls/sample.tm\n',
        encoding='utf-8',
    )
    project_without_plugin.mkdir()

    source_text = 'dsl::define greet {{name}} {puts $name}\ngreet World\n'
    source_with_plugin = project_with_plugin / 'main.tcl'
    source_with_plugin.write_text(source_text, encoding='utf-8')
    source_without_plugin = project_without_plugin / 'main.tcl'
    source_without_plugin.write_text(source_text, encoding='utf-8')

    assert check_project(source_with_plugin).diagnostics == ()

    report = check_project(source_without_plugin)

    assert len(report.diagnostics) == 2
    assert all(item.diagnostic.code == 'unresolved-command' for item in report.diagnostics)


def test_check_project_repo_root_uses_pkgindex_workspaces_and_shared_tcllsrc(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'workspace'
    package_root = project_root / 'pkg'
    plugin_path = _write_sample_plugin_bundle(project_root / '.tcl-ls')
    package_root.mkdir(parents=True)

    (project_root / 'tcllsrc.tcl').write_text(
        'plugin-path .tcl-ls/sample.tm\n',
        encoding='utf-8',
    )
    (project_root / 'scratch.tcl').write_text(
        'missing_command\n',
        encoding='utf-8',
    )
    (package_root / 'pkgIndex.tcl').write_text(
        'package ifneeded demo 1.0 [list source [file join $dir main.tcl]]\n',
        encoding='utf-8',
    )
    (package_root / 'main.tcl').write_text(
        'package provide demo 1.0\ndsl::define greet {{name}} {puts $name}\ngreet World\n',
        encoding='utf-8',
    )

    report = check_project(project_root)

    assert plugin_path.is_file()
    assert report.source_count == 2
    assert report.diagnostics == ()


def test_check_project_resolves_sourced_tcltest_imports(tmp_path: Path) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    (project_root / 'helper.inc').write_text(
        'package require tcltest\nnamespace import -force ::tcltest::*\n',
        encoding='utf-8',
    )
    (project_root / 'main.test').write_text(
        'source [file join [file dirname [info script]] helper.inc]\n'
        'test demo {} -body {return ok}\n'
        '::tcltest::cleanupTests\n',
        encoding='utf-8',
    )

    report = check_project(project_root)

    assert report.source_count == 1
    assert report.background_source_count == 1
    assert report.diagnostics == ()


def test_check_project_resolves_implicit_tcltest_in_test_tcl_files(tmp_path: Path) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    (project_root / 'main.test.tcl').write_text(
        'test demo {} -body {return ok}\n',
        encoding='utf-8',
    )

    report = check_project(project_root)

    assert report.source_count == 1
    assert report.diagnostics == ()


def test_check_project_resolves_required_tk_commands(tmp_path: Path) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    (project_root / 'main.tcl').write_text(
        'package require Tk\nframe .f\npack .f\nwm title . "Demo"\n',
        encoding='utf-8',
    )

    report = check_project(project_root)

    assert report.source_count == 1
    assert report.diagnostics == ()


def test_check_project_isolates_package_files_from_unreferenced_variants(tmp_path: Path) -> None:
    package_root = tmp_path / 'workspace' / 'demo'
    package_root.mkdir(parents=True)

    (package_root / 'pkgIndex.tcl').write_text(
        'package ifneeded demo 1.0 [list source [file join $dir main1.tcl]]\n',
        encoding='utf-8',
    )
    (package_root / 'main1.tcl').write_text(
        'package provide demo 1.0\nproc helper {} {return ok}\n',
        encoding='utf-8',
    )
    (package_root / 'main2.tcl').write_text(
        'proc helper {} {return variant}\n',
        encoding='utf-8',
    )
    (package_root / 'use.tcl').write_text(
        'package require demo\nhelper\n',
        encoding='utf-8',
    )

    report = check_project(package_root)

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


def test_check_project_threads_match_sequential_results(tmp_path: Path) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    (project_root / 'helper.inc').write_text(
        'proc greet {} {return ok}\n',
        encoding='utf-8',
    )
    (project_root / 'defs.tcl').write_text(
        'source [file join [file dirname [info script]] helper.inc]\n'
        'proc local_helper {} {greet}\n',
        encoding='utf-8',
    )
    (project_root / 'use.tcl').write_text(
        'local_helper\nmissing_command\n',
        encoding='utf-8',
    )

    sequential = check_project(project_root, threads=1)
    threaded = check_project(project_root, threads=2)

    assert threaded.source_count == sequential.source_count
    assert threaded.background_source_count == sequential.background_source_count
    assert [
        (
            item.path,
            item.diagnostic.code,
            item.diagnostic.span.start.offset,
            item.diagnostic.message,
        )
        for item in threaded.diagnostics
    ] == [
        (
            item.path,
            item.diagnostic.code,
            item.diagnostic.span.start.offset,
            item.diagnostic.message,
        )
        for item in sequential.diagnostics
    ]


def test_tcl_check_main_formats_report_and_can_fail_on_diagnostics(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    (project_root / 'broken.tcl').write_text('missing_command\n', encoding='utf-8')

    exit_code = main([str(project_root), '--color=never', '--threads=2'])
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
