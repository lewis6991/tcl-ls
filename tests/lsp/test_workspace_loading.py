from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from tcl_lsp.analysis import FactExtractor, Resolver
from tcl_lsp.lsp import workspace_rebuild as lsp_workspace_rebuild
from tcl_lsp.parser import ParseResult
from tests.lsp_service import LanguageService
from tests.project_support import (
    write_sample_library_root,
    write_sample_plugin_bundle,
    write_transitive_package_workspace,
)


def test_language_service_loads_plugin_metadata_from_tcllsrc(tmp_path: Path) -> None:
    project_root = tmp_path / 'workspace'
    write_sample_plugin_bundle(project_root / '.tcl-ls')
    (project_root / 'tcllsrc.tcl').write_text(
        'plugin-path .tcl-ls/sample.tcl\n',
        encoding='utf-8',
    )
    source_path = project_root / 'main.tcl'
    source_text = 'dsl::define greet {{name}} {puts $name}\ngreet World\n'
    source_path.write_text(source_text, encoding='utf-8')

    service = LanguageService()
    diagnostics = service.open_document(source_path.as_uri(), source_text, 1)

    assert diagnostics == ()


def test_language_service_loads_package_indexes_from_tcllsrc_lib_path(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'workspace'
    write_sample_library_root(tmp_path / 'tcllib')
    project_root.mkdir()
    (project_root / 'tcllsrc.tcl').write_text(
        'lib-path ../tcllib\n',
        encoding='utf-8',
    )
    source_path = project_root / 'main.tcl'
    source_text = 'package require samplelib\nsamplelib::greet\n'
    source_path.write_text(source_text, encoding='utf-8')

    service = LanguageService()
    diagnostics = service.open_document(source_path.as_uri(), source_text, 1)

    assert diagnostics == ()
    hover = service.hover(source_path.as_uri(), 1, 1)
    assert hover is not None
    assert hover.contents == 'proc ::samplelib::greet()'


def test_language_service_resolves_transitive_required_packages(tmp_path: Path) -> None:
    source_path = write_transitive_package_workspace(tmp_path / 'workspace')
    source_text = source_path.read_text(encoding='utf-8')

    service = LanguageService()
    diagnostics = service.open_document(source_path.as_uri(), source_text, 1)

    assert diagnostics == ()
    hover = service.hover(source_path.as_uri(), 1, 1)
    assert hover is not None
    assert hover.contents.startswith('builtin command json::json2dict {jsonText}')
    assert '\n\n---\n\n' in hover.contents
    assert 'Imported via: helper -> json (transitive)' in hover.contents


def test_language_service_hover_omits_tcl_transitive_import_notes(
    service: LanguageService,
    tmp_path: Path,
) -> None:
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
        'package require Tcl\npackage provide helper 1.0\n',
        encoding='utf-8',
    )

    main_uri = (app_dir / 'main.tcl').as_uri()
    diagnostics = service.open_document(main_uri, 'package require helper\nclock seconds\n', 1)

    assert diagnostics == ()
    hover = service.hover(main_uri, 1, 1)
    assert hover is not None
    assert hover.contents.startswith('builtin command clock ')
    assert 'Imported via:' not in hover.contents


def test_language_service_uses_helper_metadata_for_embedded_dependencies(
    tmp_path: Path,
) -> None:
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
    helper_path = package_root / 'helper.tcl'
    helper_path.write_text(
        'proc helper {} {return ok}\n',
        encoding='utf-8',
    )

    source_path = package_root / 'main.test'
    source_text = (
        'source [file join [file dirname [file dirname [info script]]] devtools testutilities.tcl]\n'
        'testing {\n'
        '    useLocal helper.tcl demo\n'
        '    testsNeed Tk 8.5\n'
        '}\n'
        'helper\n'
        'frame .f\n'
    )
    source_path.write_text(source_text, encoding='utf-8')

    service = LanguageService()
    diagnostics = service.open_document(source_path.as_uri(), source_text, 1)

    assert diagnostics == ()

    helper_definitions = service.definition(source_path.as_uri(), 5, 1)
    assert len(helper_definitions) == 1
    assert helper_definitions[0].uri == helper_path.as_uri()

    hover = service.hover(source_path.as_uri(), 6, 1)
    assert hover is not None
    assert hover.contents.startswith('builtin command frame ')


def test_language_service_loads_generated_project_metadata_without_docs(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'workspace'
    write_sample_plugin_bundle(project_root / '.tcl-ls')
    (project_root / '.tcl-ls' / 'generated.meta.tcl').write_text(
        'meta module Tcl\nmeta command external {args}\n',
        encoding='utf-8',
    )
    (project_root / 'tcllsrc.tcl').write_text(
        'plugin-path .tcl-ls/sample.tcl\n',
        encoding='utf-8',
    )
    source_path = project_root / 'main.tcl'
    source_text = 'external run\n'
    source_path.write_text(source_text, encoding='utf-8')

    service = LanguageService()
    diagnostics = service.open_document(source_path.as_uri(), source_text, 1)

    assert diagnostics == ()
    hover = service.hover(source_path.as_uri(), 0, 1)
    assert hover is not None
    assert hover.contents == 'builtin command external {args}'


def test_language_service_clears_project_metadata_when_plugin_paths_change(
    tmp_path: Path,
) -> None:
    project_with_plugin = tmp_path / 'with-plugin'
    project_without_plugin = tmp_path / 'without-plugin'
    write_sample_plugin_bundle(project_with_plugin / '.tcl-ls')
    (project_with_plugin / 'tcllsrc.tcl').write_text(
        'plugin-path .tcl-ls/sample.tcl\n',
        encoding='utf-8',
    )
    project_without_plugin.mkdir()

    source_text = 'dsl::define greet {{name}} {puts $name}\ngreet World\n'
    source_with_plugin = project_with_plugin / 'main.tcl'
    source_with_plugin.write_text(source_text, encoding='utf-8')
    source_without_plugin = project_without_plugin / 'main.tcl'
    source_without_plugin.write_text(source_text, encoding='utf-8')

    service = LanguageService()
    assert service.open_document(source_with_plugin.as_uri(), source_text, 1) == ()

    service.close_document(source_with_plugin.as_uri())
    diagnostics = service.open_document(source_without_plugin.as_uri(), source_text, 1)

    assert len(diagnostics) == 2
    assert all(diagnostic.code == 'unresolved-command' for diagnostic in diagnostics)


def test_language_service_isolates_project_metadata_between_services(
    tmp_path: Path,
) -> None:
    project_with_plugin = tmp_path / 'with-plugin'
    project_without_plugin = tmp_path / 'without-plugin'
    write_sample_plugin_bundle(project_with_plugin / '.tcl-ls')
    (project_with_plugin / 'tcllsrc.tcl').write_text(
        'plugin-path .tcl-ls/sample.tcl\n',
        encoding='utf-8',
    )
    project_without_plugin.mkdir()

    source_text = 'dsl::define greet {{name}} {puts $name}\ngreet World\n'
    source_with_plugin = project_with_plugin / 'main.tcl'
    source_with_plugin.write_text(source_text, encoding='utf-8')
    source_without_plugin = project_without_plugin / 'main.tcl'
    source_without_plugin.write_text(source_text, encoding='utf-8')

    service_with_plugin = LanguageService()
    service_without_plugin = LanguageService()

    assert service_with_plugin.open_document(source_with_plugin.as_uri(), source_text, 1) == ()

    diagnostics = service_without_plugin.open_document(
        source_without_plugin.as_uri(), source_text, 1
    )

    assert len(diagnostics) == 2
    assert all(diagnostic.code == 'unresolved-command' for diagnostic in diagnostics)

    hover = service_with_plugin.hover(source_with_plugin.as_uri(), 1, 1)
    assert hover is not None
    assert hover.contents == 'proc ::greet(name)'


def test_language_service_clears_project_library_paths_when_project_changes(
    tmp_path: Path,
) -> None:
    project_with_lib = tmp_path / 'with-lib'
    project_without_lib = tmp_path / 'without-lib'
    write_sample_library_root(tmp_path / 'tcllib')
    project_with_lib.mkdir()
    project_without_lib.mkdir()
    (project_with_lib / 'tcllsrc.tcl').write_text(
        'lib-path ../tcllib\n',
        encoding='utf-8',
    )

    source_text = 'package require samplelib\nsamplelib::greet\n'
    source_with_lib = project_with_lib / 'main.tcl'
    source_with_lib.write_text(source_text, encoding='utf-8')
    source_without_lib = project_without_lib / 'main.tcl'
    source_without_lib.write_text(source_text, encoding='utf-8')

    service = LanguageService()
    assert service.open_document(source_with_lib.as_uri(), source_text, 1) == ()

    service.close_document(source_with_lib.as_uri())
    diagnostics = service.open_document(source_without_lib.as_uri(), source_text, 1)

    assert [diagnostic.code for diagnostic in diagnostics] == ['unresolved-package']


def test_language_service_infers_packages_from_pkgindex(
    service: LanguageService,
    tmp_path: Path,
) -> None:
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

    main_uri = (app_dir / 'main.tcl').as_uri()
    diagnostics = service.open_document(main_uri, 'package require helper\nhelper::greet\n', 1)

    assert diagnostics == ()

    definition_locations = service.definition(main_uri, 1, 2)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == (helper_dir / 'helper.tcl').as_uri()

    hover = service.hover(main_uri, 1, 2)
    assert hover is not None
    assert hover.contents == 'proc ::helper::greet()'


def test_language_service_only_loads_required_package_index(
    service: LanguageService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modules_root = tmp_path / 'workspace' / 'modules'
    helper_dir = modules_root / 'helper'
    unused_dir = modules_root / 'unused'
    app_dir = modules_root / 'app'
    helper_dir.mkdir(parents=True)
    unused_dir.mkdir()
    app_dir.mkdir()

    helper_pkg_index = helper_dir / 'pkgIndex.tcl'
    helper_pkg_index.write_text(
        'package ifneeded helper 1.0 [list source [file join $dir helper.tcl]]\n',
        encoding='utf-8',
    )
    (helper_dir / 'helper.tcl').write_text(
        'package provide helper 1.0\nproc helper::greet {} {return ok}\n',
        encoding='utf-8',
    )
    unused_pkg_index = unused_dir / 'pkgIndex.tcl'
    unused_pkg_index.write_text(
        'package ifneeded unused 1.0 [list source [file join $dir unused.tcl]]\n',
        encoding='utf-8',
    )
    (unused_dir / 'unused.tcl').write_text(
        'package provide unused 1.0\nproc unused::noop {} {return ok}\n',
        encoding='utf-8',
    )

    loaded_pkg_indexes: list[Path] = []
    original_load_package_index = lsp_workspace_rebuild.load_package_index

    def counting_load_package_index(
        path: Path,
        *,
        parser: object | None = None,
    ) -> object:
        loaded_pkg_indexes.append(path.resolve(strict=False))
        return original_load_package_index(path, parser=cast(Any, parser))

    monkeypatch.setattr(lsp_workspace_rebuild, 'load_package_index', counting_load_package_index)

    main_uri = (app_dir / 'main.tcl').as_uri()
    diagnostics = service.open_document(main_uri, 'package require helper\nhelper::greet\n', 1)

    assert diagnostics == ()
    assert loaded_pkg_indexes == [helper_pkg_index.resolve(strict=False)]
    assert unused_pkg_index.resolve(strict=False) not in loaded_pkg_indexes


def test_language_service_only_loads_required_package_index_when_package_name_differs_from_directory(
    service: LanguageService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modules_root = tmp_path / 'workspace' / 'modules'
    grammar_fa_dir = modules_root / 'grammar_fa'
    unused_dir = modules_root / 'unused'
    app_dir = modules_root / 'app'
    grammar_fa_dir.mkdir(parents=True)
    unused_dir.mkdir()
    app_dir.mkdir()

    grammar_pkg_index = grammar_fa_dir / 'pkgIndex.tcl'
    grammar_pkg_index.write_text(
        'package ifneeded grammar::fa 1.0 [list source [file join $dir fa.tcl]]\n',
        encoding='utf-8',
    )
    (grammar_fa_dir / 'fa.tcl').write_text(
        'package provide grammar::fa 1.0\nproc grammar::fa::run {} {return ok}\n',
        encoding='utf-8',
    )
    unused_pkg_index = unused_dir / 'pkgIndex.tcl'
    unused_pkg_index.write_text(
        'package ifneeded unused::pkg 1.0 [list source [file join $dir unused.tcl]]\n',
        encoding='utf-8',
    )
    (unused_dir / 'unused.tcl').write_text(
        'package provide unused::pkg 1.0\nproc unused::pkg::run {} {return ok}\n',
        encoding='utf-8',
    )

    loaded_pkg_indexes: list[Path] = []
    original_load_package_index = lsp_workspace_rebuild.load_package_index

    def counting_load_package_index(
        path: Path,
        *,
        parser: object | None = None,
    ) -> object:
        loaded_pkg_indexes.append(path.resolve(strict=False))
        return original_load_package_index(path, parser=cast(Any, parser))

    monkeypatch.setattr(lsp_workspace_rebuild, 'load_package_index', counting_load_package_index)

    main_uri = (app_dir / 'main.tcl').as_uri()
    diagnostics = service.open_document(
        main_uri,
        'package require grammar::fa\ngrammar::fa::run\n',
        1,
    )

    assert diagnostics == ()
    assert loaded_pkg_indexes == [grammar_pkg_index.resolve(strict=False)]
    assert unused_pkg_index.resolve(strict=False) not in loaded_pkg_indexes


def test_language_service_open_document_only_fully_analyzes_open_documents(
    service: LanguageService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modules_root = tmp_path / 'workspace' / 'modules'
    helper_dir = modules_root / 'helper'
    app_dir = modules_root / 'app'
    helper_dir.mkdir(parents=True)
    app_dir.mkdir()

    (helper_dir / 'pkgIndex.tcl').write_text(
        'package ifneeded helper 1.0 [list source [file join $dir helper.tcl]]\n',
        encoding='utf-8',
    )
    helper_path = helper_dir / 'helper.tcl'
    helper_path.write_text(
        'package provide helper 1.0\nproc helper::greet {} {return ok}\n',
        encoding='utf-8',
    )

    analyzed_uris: list[str] = []
    original_analyze = Resolver.analyze

    def counting_analyze(
        self: Resolver,
        uri: str,
        facts: object,
        workspace_index: object,
        *,
        additional_required_packages: frozenset[str] = frozenset(),
    ) -> object:
        analyzed_uris.append(uri)
        return original_analyze(
            self,
            uri,
            cast(Any, facts),
            cast(Any, workspace_index),
            additional_required_packages=additional_required_packages,
        )

    monkeypatch.setattr(Resolver, 'analyze', counting_analyze)

    main_uri = (app_dir / 'main.tcl').as_uri()
    diagnostics = service.open_document(main_uri, 'package require helper\nhelper::greet\n', 1)

    assert diagnostics == ()
    assert analyzed_uris == [main_uri]
    definition_locations = service.definition(main_uri, 1, 2)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == helper_path.as_uri()


def test_language_service_reuses_cached_background_documents_until_disk_content_changes(
    service: LanguageService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modules_root = tmp_path / 'workspace' / 'modules'
    helper_dir = modules_root / 'helper'
    app_dir = modules_root / 'app'
    helper_dir.mkdir(parents=True)
    app_dir.mkdir()

    (helper_dir / 'pkgIndex.tcl').write_text(
        'package ifneeded helper 1.0 [list source [file join $dir helper.tcl]]\n',
        encoding='utf-8',
    )
    helper_path = helper_dir / 'helper.tcl'
    helper_path.write_text(
        'package provide helper 1.0\nproc helper::greet {} {return ok}\n',
        encoding='utf-8',
    )

    extract_counts: dict[str, int] = {}
    original_extract = FactExtractor.extract

    def counting_extract(
        self: FactExtractor,
        parse_result: object,
        *args: object,
        **kwargs: object,
    ) -> object:
        source_id = cast(ParseResult, parse_result).source_id
        extract_counts[source_id] = extract_counts.get(source_id, 0) + 1
        return original_extract(self, cast(Any, parse_result), *args, **kwargs)

    monkeypatch.setattr(FactExtractor, 'extract', counting_extract)

    main_uri = (app_dir / 'main.tcl').as_uri()
    helper_uri = helper_path.as_uri()

    assert service.open_document(main_uri, 'package require helper\nhelper::greet\n', 1) == ()
    first_helper_extracts = extract_counts.get(helper_uri, 0)
    assert first_helper_extracts > 0

    service.close_document(main_uri)
    assert service.open_document(main_uri, 'package require helper\nhelper::greet\n', 2) == ()
    assert extract_counts.get(helper_uri, 0) == first_helper_extracts

    service.close_document(main_uri)
    helper_path.write_text(
        'package provide helper 1.0\nproc helper::wave {} {return ok}\n',
        encoding='utf-8',
    )

    assert service.open_document(main_uri, 'package require helper\nhelper::wave\n', 3) == ()
    assert extract_counts.get(helper_uri, 0) == first_helper_extracts + 1


def test_language_service_clears_cached_background_documents_when_plugin_paths_change(
    tmp_path: Path,
) -> None:
    shared_root = tmp_path / 'shared'
    helper_dir = shared_root / 'helper'
    helper_dir.mkdir(parents=True)
    (helper_dir / 'pkgIndex.tcl').write_text(
        'package ifneeded helper 1.0 [list source [file join $dir helper.tcl]]\n',
        encoding='utf-8',
    )
    (helper_dir / 'helper.tcl').write_text(
        'package provide helper 1.0\ndsl::define greet {{name}} {puts $name}\n',
        encoding='utf-8',
    )

    project_with_plugin = tmp_path / 'with-plugin'
    project_without_plugin = tmp_path / 'without-plugin'
    write_sample_plugin_bundle(project_with_plugin / '.tcl-ls')
    project_with_plugin.mkdir(exist_ok=True)
    project_without_plugin.mkdir()

    (project_with_plugin / 'tcllsrc.tcl').write_text(
        'plugin-path .tcl-ls/sample.tcl\nlib-path ../shared\n',
        encoding='utf-8',
    )
    (project_without_plugin / 'tcllsrc.tcl').write_text(
        'lib-path ../shared\n',
        encoding='utf-8',
    )

    source_text = 'package require helper\ngreet World\n'
    source_with_plugin = project_with_plugin / 'main.tcl'
    source_with_plugin.write_text(source_text, encoding='utf-8')
    source_without_plugin = project_without_plugin / 'main.tcl'
    source_without_plugin.write_text(source_text, encoding='utf-8')

    service = LanguageService()
    assert service.open_document(source_with_plugin.as_uri(), source_text, 1) == ()

    service.close_document(source_with_plugin.as_uri())
    diagnostics = service.open_document(source_without_plugin.as_uri(), source_text, 1)

    assert [diagnostic.code for diagnostic in diagnostics] == ['unresolved-command']


def test_language_service_file_targets_prefer_nearest_pkgindex_root(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / 'workspace'
    package_root = workspace_root / 'tcl'
    sibling_package_root = workspace_root / 'helper'
    package_root.mkdir(parents=True)
    sibling_package_root.mkdir()

    (package_root / 'pkgIndex.tcl').write_text(
        'package ifneeded demo 1.0 [list source [file join $dir demo.tcl]]\n',
        encoding='utf-8',
    )
    (package_root / 'demo.tcl').write_text(
        'package provide demo 1.0\nproc demo::run {} {return ok}\n',
        encoding='utf-8',
    )
    (sibling_package_root / 'pkgIndex.tcl').write_text(
        'package ifneeded helper 1.0 [list source [file join $dir helper.tcl]]\n',
        encoding='utf-8',
    )
    (sibling_package_root / 'helper.tcl').write_text(
        'package provide helper 1.0\nproc helper::greet {} {return ok}\n',
        encoding='utf-8',
    )

    main_uri = (package_root / 'main.tcl').as_uri()
    diagnostics = service.open_document(main_uri, 'package require helper\nhelper::greet\n', 1)

    assert [diagnostic.code for diagnostic in diagnostics] == ['unresolved-package']
    assert len(tuple(service.server.workspace_index.package_indexes())) == 1


def test_language_service_prunes_unreachable_background_documents_on_change(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    modules_root = tmp_path / 'workspace' / 'modules'
    helper_dir = modules_root / 'helper'
    app_dir = modules_root / 'app'
    helper_dir.mkdir(parents=True)
    app_dir.mkdir()

    (helper_dir / 'pkgIndex.tcl').write_text(
        'package ifneeded helper 1.0 [list source [file join $dir helper.tcl]]\n',
        encoding='utf-8',
    )
    helper_path = helper_dir / 'helper.tcl'
    helper_path.write_text(
        'package provide helper 1.0\nproc helper::greet {} {return ok}\n',
        encoding='utf-8',
    )

    main_uri = (app_dir / 'main.tcl').as_uri()
    assert service.open_document(main_uri, 'package require helper\nhelper::greet\n', 1) == ()
    assert helper_path.as_uri() in service.server.documents

    diagnostics = service.change_document(main_uri, 'helper::greet\n', 2)

    assert [diagnostic.code for diagnostic in diagnostics] == ['unresolved-command']
    assert helper_path.as_uri() not in service.server.documents


def test_language_service_definition_resolves_required_package_to_provider(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    modules_root = tmp_path / 'workspace' / 'modules'
    helper_dir = modules_root / 'helper'
    app_dir = modules_root / 'app'
    helper_dir.mkdir(parents=True)
    app_dir.mkdir()

    (helper_dir / 'pkgIndex.tcl').write_text(
        'package ifneeded helper 1.0 [list source [file join $dir helper.tcl]]\n',
        encoding='utf-8',
    )
    helper_path = helper_dir / 'helper.tcl'
    helper_path.write_text(
        'package provide helper 1.0\nproc helper::greet {} {return ok}\n',
        encoding='utf-8',
    )

    main_uri = (app_dir / 'main.tcl').as_uri()
    diagnostics = service.open_document(main_uri, 'package require helper\nhelper::greet\n', 1)

    assert diagnostics == ()

    definition_locations = service.definition(main_uri, 0, 17)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == helper_path.as_uri()
    assert definition_locations[0].range.start.line == 0
    assert definition_locations[0].range.start.character == 16


def test_language_service_hover_notes_imported_package_commands(
    service: LanguageService,
    tmp_path: Path,
) -> None:
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
        'package provide helper 1.0\n# Greets helper callers.\nproc helper::greet {} {return ok}\n',
        encoding='utf-8',
    )

    main_uri = (app_dir / 'main.tcl').as_uri()
    diagnostics = service.open_document(
        main_uri,
        'package require helper\nnamespace import ::helper::*\ngreet\n',
        1,
    )

    assert diagnostics == ()
    hover = service.hover(main_uri, 2, 1)
    assert hover is not None
    assert (
        hover.contents
        == 'proc ::helper::greet()\n\nGreets helper callers.\n\n---\n\nImported via: ::helper::*'
    )


def test_language_service_definition_resolves_namespace_import_patterns(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    modules_root = tmp_path / 'workspace' / 'modules'
    helper_dir = modules_root / 'helper'
    app_dir = modules_root / 'app'
    helper_dir.mkdir(parents=True)
    app_dir.mkdir()

    (helper_dir / 'pkgIndex.tcl').write_text(
        'package ifneeded helper 1.0 [list source [file join $dir helper.tcl]]\n',
        encoding='utf-8',
    )
    helper_path = helper_dir / 'helper.tcl'
    helper_path.write_text(
        'package provide helper 1.0\nproc helper::greet {} {return ok}\n',
        encoding='utf-8',
    )

    main_uri = (app_dir / 'main.tcl').as_uri()
    diagnostics = service.open_document(
        main_uri,
        'package require helper\nnamespace import ::helper::*\n',
        1,
    )

    assert diagnostics == ()

    definition_locations = service.definition(main_uri, 1, 20)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == helper_path.as_uri()
    assert definition_locations[0].range.start.line == 1
    assert definition_locations[0].range.start.character == 5


def test_language_service_loads_static_source_commands(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    helper_path = project_root / 'helper.inc'
    helper_path.write_text(
        'proc greet {} {return ok}\n',
        encoding='utf-8',
    )

    main_uri = (project_root / 'main.tcl').as_uri()
    diagnostics = service.open_document(
        main_uri,
        'source [file join [file dirname [info script]] helper.inc]\ngreet\n',
        1,
    )

    assert diagnostics == ()

    definition_locations = service.definition(main_uri, 1, 2)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == helper_path.as_uri()

    hover = service.hover(main_uri, 1, 2)
    assert hover is not None
    assert hover.contents == 'proc ::greet()'


def test_language_service_unloads_removed_static_source_commands(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    (project_root / 'helper.inc').write_text(
        'proc greet {} {return ok}\n',
        encoding='utf-8',
    )

    main_uri = (project_root / 'main.tcl').as_uri()
    assert (
        service.open_document(
            main_uri,
            'source [file join [file dirname [info script]] helper.inc]\ngreet\n',
            1,
        )
        == ()
    )

    diagnostics = service.change_document(main_uri, 'greet\n', 2)

    assert [diagnostic.code for diagnostic in diagnostics] == ['unresolved-command']
    assert diagnostics[0].message == 'Unresolved command `greet`.'


def test_language_service_removed_static_source_ignores_other_open_helper_window(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    helper_path = project_root / 'helper.inc'
    helper_path.write_text(
        'proc greet {} {return ok}\n',
        encoding='utf-8',
    )

    main_uri = (project_root / 'main.tcl').as_uri()
    helper_uri = helper_path.as_uri()
    assert (
        service.open_document(
            main_uri,
            'source [file join [file dirname [info script]] helper.inc]\ngreet\n',
            1,
        )
        == ()
    )
    assert service.open_document(helper_uri, helper_path.read_text(encoding='utf-8'), 1) == ()

    diagnostics = service.change_document(main_uri, 'greet\n', 2)

    assert [diagnostic.code for diagnostic in diagnostics] == ['unresolved-command']
    assert diagnostics[0].message == 'Unresolved command `greet`.'


def test_language_service_resolves_sourced_tcltest_imports(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    (project_root / 'helper.inc').write_text(
        'package require tcltest\nnamespace import -force ::tcltest::*\n',
        encoding='utf-8',
    )

    main_uri = (project_root / 'main.test').as_uri()
    diagnostics = service.open_document(
        main_uri,
        'source [file join [file dirname [info script]] helper.inc]\n'
        'test demo {} -body {return ok}\n'
        '::tcltest::cleanupTests\n',
        1,
    )

    assert diagnostics == ()

    hover = service.hover(main_uri, 1, 1)
    assert hover is not None
    assert hover.contents.startswith('builtin command tcltest::test')
    assert 'Imported via: helper.inc -> ::tcltest::*' in hover.contents
    assert 'Imported via: helper.inc -> tcltest (transitive)' in hover.contents

    qualified_hover = service.hover(main_uri, 2, 3)
    assert qualified_hover is not None
    assert qualified_hover.contents.startswith('builtin command tcltest::cleanupTests')
    assert 'Imported via: helper.inc -> tcltest (transitive)' in qualified_hover.contents


def test_language_service_reports_unresolved_packages(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    main_uri = (tmp_path / 'missing.tcl').as_uri()

    diagnostics = service.open_document(main_uri, 'package require missing\nmissing::run\n', 1)

    assert [diagnostic.code for diagnostic in diagnostics] == ['unresolved-package']
