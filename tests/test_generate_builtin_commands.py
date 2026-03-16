from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_GENERATOR_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'generate_builtin_commands.py'


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location('generate_builtin_commands', _GENERATOR_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_update_metadata_inserts_generated_subcommand_blocks() -> None:
    generator = _load_generator()
    source_text = (
        '# Tcl builtin command metadata for tcl-ls.\n'
        '# Descriptions are adapted from the Tcl 8.6 command manual.\n'
        'meta command dict {subcommand args}\n'
        'meta command puts {args}\n'
    )
    docs_by_command = {
        'dict': (
            '<DT><A NAME="M1"><B>dict get </B><I>dictionaryValue </I>?<I>key ...</I>?'
            '</A><DD>Return a nested value.</DD>'
            '<DT><A NAME="M2"><B>dict filter </B><I>dictionaryValue filterType arg ?arg ...?</I>'
            '</A><DD>Filter dictionary values.</DD>'
            '<DT><A NAME="M3"><B>dict filter </B><I>dictionaryValue </I><B>key</B> '
            '?<I>globPattern ...</I>?</A><DD>Filter dictionary entries by key.</DD>'
        )
    }

    updated = generator.update_metadata(
        source_text=source_text,
        docs_by_command=docs_by_command,
        version_label='8.6',
    )

    assert 'meta command dict {subcommand args} {' in updated
    assert '    # @generated begin subcommands for dict (Tcl 8.6)' in updated
    assert '    subcommand get {dictionaryValue ? key ... ?}' in updated
    assert '    subcommand filter {dictionaryValue filterType arg ?arg ...?} {' in updated
    assert '        subcommand key {dictionaryValue ?globPattern ...?}' in updated
    assert '    # @generated end subcommands for dict' in updated
    assert 'meta command {dict get} {dictionaryValue ? key ... ?}' not in updated
    assert generator.update_metadata(updated, docs_by_command, version_label='8.6') == updated


def test_extract_entries_from_html_keeps_nested_subcommand_names() -> None:
    generator = _load_generator()
    html_text = (
        '<DT><A NAME="M1"><B>trace add </B><I>type name ops ?args?</I></A><DD>'
        'Add a trace.</DD>'
        '<DT><A NAME="M2"><B>trace add command</B> <I>name ops commandPrefix</I></A><DD>'
        'Trace command changes.</DD>'
        '<DT><A NAME="M3"><B>trace add variable</B><I> name ops commandPrefix</I></A><DD>'
        'Trace variable access.</DD>'
    )

    entries = generator.extract_entries_from_html(command='trace', html_text=html_text)

    assert [entry.name for entry in entries] == [
        'trace add',
        'trace add command',
        'trace add variable',
    ]
    assert entries[1].params == 'name ops commandPrefix'
    assert entries[1].documentation == 'Trace command changes.'
