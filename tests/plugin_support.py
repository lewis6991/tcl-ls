from __future__ import annotations

from pathlib import Path

from tcl_lsp.metadata_paths import bundled_metadata_dir


def write_header_plugin(
    directory: Path, *, hook: str = 'shared', metadata_name: str = 'tcllsrc.tcl'
) -> Path:
    fixture = Path(__file__).parent / 'fixtures/plugins/shared-header.tcl'
    plugin = directory / 'header.tcl'
    library = bundled_metadata_dir() / 'tcllib/tepam-plugin.tcl'
    plugin.write_text(library.read_text() + '\n' + fixture.read_text(), encoding='utf-8')
    (directory / metadata_name).write_text(
        'meta module Tcl {\n'
        '    meta command declare {name header body} {\n'
        '        procedure {\n'
        '            name {select 1}\n'
        f'            params {{select 2 plugin {{header.tcl ::tepam::metadata::{hook}}}}}\n'
        + ('            body {select 3}\n' if hook != 'declaration' else '')
        + '        }\n'
        '    }\n'
        '}\n',
        encoding='utf-8',
    )
    return plugin
