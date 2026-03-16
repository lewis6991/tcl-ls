#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import re
import sys
import textwrap
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_METADATA_PATH = _REPO_ROOT / 'meta' / 'tcl8.6' / 'tcl.tcl'
_DEFAULT_DOC_ROOT_TEMPLATE = 'https://www.tcl-lang.org/man/tcl{series}/TclCmd'
_GENERATOR_NOTE = (
    '# Generated subcommand sections are maintained by '
    'scripts/generate_builtin_commands.py.'
)
_DESCRIPTION_LINE_PATTERN = re.compile(
    r'^# Descriptions are adapted from the Tcl .+ command manual\.$',
    re.MULTILINE,
)
_META_COMMAND_NAME_PATTERN = re.compile(r'^meta command (\{[^}]+\}|\S+) ', re.MULTILINE)
_GENERIC_SUBCOMMAND_PATTERN = re.compile(r'^meta command (\S+) \{subcommand(?: [^}]*)?\}$')
_DT_PATTERN = re.compile(
    r'<DT><A NAME="[^"]+">(.*?)</A><DD>(.*?)(?=<P><DT><A NAME=|<DT><A NAME=|'
    r'<P></DL>|</DL>|<H3><A NAME=|$)',
    re.DOTALL,
)
_GENERATED_BEGIN_PREFIX = '# @generated begin subcommands for '
_GENERATED_END_PREFIX = '# @generated end subcommands for '
_REQUEST_HEADERS = {'User-Agent': 'Mozilla/5.0'}


@dataclass(frozen=True, slots=True)
class GeneratedEntry:
    name: str
    params: str
    documentation: str


_MANUAL_ENTRIES: dict[str, tuple[GeneratedEntry, ...]] = {
    'binary': (
        GeneratedEntry(
            name='binary decode',
            params='format ?-option value ...? data',
            documentation='Convert encoded text to binary data using the specified format.',
        ),
        GeneratedEntry(
            name='binary decode base64',
            params='data ?-strict?',
            documentation='Decode base64 text into binary data.',
        ),
        GeneratedEntry(
            name='binary decode hex',
            params='data ?-strict?',
            documentation='Decode hexadecimal text into binary data.',
        ),
        GeneratedEntry(
            name='binary decode uuencode',
            params='data ?-strict?',
            documentation='Decode uuencoded text into binary data.',
        ),
        GeneratedEntry(
            name='binary encode',
            params='format ?-option value ...? data',
            documentation='Convert binary data to an encoded string using the specified format.',
        ),
        GeneratedEntry(
            name='binary encode base64',
            params='data ?-maxlen length? ?-wrapchar character?',
            documentation='Encode binary data as base64 text.',
        ),
        GeneratedEntry(
            name='binary encode hex',
            params='data',
            documentation='Encode binary data as hexadecimal text.',
        ),
        GeneratedEntry(
            name='binary encode uuencode',
            params='data ?-maxlen length? ?-wrapchar character?',
            documentation='Encode binary data as uuencoded text.',
        ),
        GeneratedEntry(
            name='binary format',
            params='formatString ?arg arg ...?',
            documentation='Generate a binary string from the values described by formatString.',
        ),
        GeneratedEntry(
            name='binary scan',
            params='string formatString ?varName varName ...?',
            documentation='Parse fields from a binary string into Tcl variables.',
        ),
    )
}

_OVERRIDE_DOCS = {
    'interp children': 'Alias for interp slaves.',
    'package prefer': 'Get or set whether package selection prefers the latest or stable '
    'version.',
}

_OVERRIDE_PARAMS = {
    'dict filter key': 'dictionaryValue ?globPattern ...?',
    'dict filter script': 'dictionaryValue {keyVariable valueVariable} script',
    'dict filter value': 'dictionaryValue ?globPattern ...?',
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Refresh generated builtin subcommand metadata blocks from Tcl command docs.'
    )
    parser.add_argument(
        '--input',
        type=Path,
        default=_DEFAULT_METADATA_PATH,
        help='Metadata file to read and update in memory.',
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=None,
        help='Destination metadata file. Defaults to overwriting --input.',
    )
    parser.add_argument(
        '--doc-root',
        default=None,
        help='Directory or base URL containing Tcl command manual pages.',
    )
    parser.add_argument(
        '--tcl-doc-series',
        default='8.6',
        help='Tcl doc series used for the default online doc root, e.g. 8.6 or 8.7.',
    )
    parser.add_argument(
        '--version-label',
        default=None,
        help='Version label recorded in the generated file header.',
    )
    parser.add_argument(
        '--check',
        action='store_true',
        help='Exit with status 1 instead of writing if the output would change.',
    )
    args = parser.parse_args(argv)

    output_path = args.output if args.output is not None else args.input
    version_label = args.version_label if args.version_label is not None else args.tcl_doc_series
    doc_root = (
        args.doc_root
        if args.doc_root is not None
        else _DEFAULT_DOC_ROOT_TEMPLATE.format(series=args.tcl_doc_series)
    )

    source_text = args.input.read_text(encoding='utf-8')
    docs_by_command = {
        command: load_doc_page(command=command, doc_root=doc_root)
        for command in generic_subcommand_commands(source_text)
    }
    rendered = update_metadata(
        source_text=source_text,
        docs_by_command=docs_by_command,
        version_label=version_label,
    )

    current_output = output_path.read_text(encoding='utf-8') if output_path.exists() else ''
    if args.check:
        if current_output != rendered:
            print(f'{output_path} is out of date; rerun scripts/generate_builtin_commands.py', file=sys.stderr)
            return 1
        return 0

    if current_output != rendered:
        output_path.write_text(rendered, encoding='utf-8')
    return 0


def update_metadata(
    source_text: str,
    docs_by_command: Mapping[str, str],
    version_label: str,
) -> str:
    base_text = strip_generated_blocks(source_text)
    base_text = _ensure_generator_note(base_text)
    base_text = _update_description_line(base_text, version_label)

    existing_names = meta_command_names(base_text)
    generated_entries_by_command: dict[str, tuple[GeneratedEntry, ...]] = {}

    for command in generic_subcommand_commands(base_text):
        generated_entries = build_generated_entries(
            command=command,
            html_text=docs_by_command.get(command, ''),
            existing_names=existing_names,
        )
        generated_entries_by_command[command] = generated_entries
        existing_names.update(entry.name for entry in generated_entries)

    rendered_lines: list[str] = []
    for line in base_text.splitlines():
        rendered_lines.append(line)
        match = _GENERIC_SUBCOMMAND_PATTERN.fullmatch(line)
        if match is None:
            continue

        command = match.group(1)
        generated_entries = generated_entries_by_command.get(command, ())
        if not generated_entries:
            continue

        rendered_lines.append('')
        rendered_lines.extend(render_generated_block(command, generated_entries, version_label))

    return '\n'.join(rendered_lines).rstrip() + '\n'


def strip_generated_blocks(source_text: str) -> str:
    result_lines: list[str] = []
    active_command: str | None = None
    skip_leading_blank_after_block = False

    for line in source_text.splitlines():
        if line.startswith(_GENERATED_BEGIN_PREFIX):
            if active_command is not None:
                raise ValueError(f'Nested generated block for `{active_command}`.')
            if result_lines and result_lines[-1] == '':
                result_lines.pop()
            active_command = line.removeprefix(_GENERATED_BEGIN_PREFIX).split(' ', maxsplit=1)[0]
            continue

        if line.startswith(_GENERATED_END_PREFIX):
            command = line.removeprefix(_GENERATED_END_PREFIX).split(' ', maxsplit=1)[0]
            if active_command != command:
                raise ValueError(
                    f'Generated block terminator for `{command}` does not match `{active_command}`.'
                )
            active_command = None
            skip_leading_blank_after_block = True
            continue

        if active_command is None:
            if skip_leading_blank_after_block and line == '':
                skip_leading_blank_after_block = False
                continue
            skip_leading_blank_after_block = False
            result_lines.append(line)

    if active_command is not None:
        raise ValueError(f'Unterminated generated block for `{active_command}`.')

    stripped = '\n'.join(result_lines).rstrip()
    stripped = re.sub(r'\n{3,}', '\n\n', stripped)
    return stripped + '\n'


def generic_subcommand_commands(source_text: str) -> tuple[str, ...]:
    stripped_text = strip_generated_blocks(source_text)
    commands: list[str] = []
    for line in stripped_text.splitlines():
        match = _GENERIC_SUBCOMMAND_PATTERN.fullmatch(line)
        if match is None:
            continue
        command = match.group(1)
        if command not in commands:
            commands.append(command)
    return tuple(commands)


def meta_command_names(source_text: str) -> set[str]:
    names: set[str] = set()
    for match in _META_COMMAND_NAME_PATTERN.finditer(source_text):
        name = match.group(1)
        if name.startswith('{') and name.endswith('}'):
            name = name[1:-1]
        names.add(name)
    return names


def build_generated_entries(
    command: str,
    html_text: str,
    existing_names: set[str],
) -> tuple[GeneratedEntry, ...]:
    raw_entries = list(extract_entries_from_html(command=command, html_text=html_text))
    raw_entries.extend(_MANUAL_ENTRIES.get(command, ()))

    first_doc_by_name: dict[str, str] = {}
    for entry in raw_entries:
        if entry.documentation:
            first_doc_by_name.setdefault(entry.name, entry.documentation)

    generated: list[GeneratedEntry] = []
    seen: set[tuple[str, str]] = set()
    for entry in raw_entries:
        if entry.name in existing_names:
            continue
        key = (entry.name, entry.params)
        if key in seen:
            continue
        seen.add(key)
        generated.append(
            GeneratedEntry(
                name=entry.name,
                params=_OVERRIDE_PARAMS.get(entry.name, entry.params),
                documentation=_OVERRIDE_DOCS.get(
                    entry.name,
                    entry.documentation or first_doc_by_name.get(entry.name, f'{entry.name} subcommand.'),
                ),
            )
        )

    return tuple(generated)


def extract_entries_from_html(command: str, html_text: str) -> tuple[GeneratedEntry, ...]:
    entries: list[GeneratedEntry] = []

    for head_html, desc_html in _DT_PATTERN.findall(html_text):
        name = _entry_name(head_html)
        if name is None or not name.startswith(f'{command} '):
            continue

        plain_heading = _strip_heading_text(head_html)
        if name in _OVERRIDE_PARAMS:
            params = _OVERRIDE_PARAMS[name]
        elif plain_heading.startswith(name):
            params = plain_heading[len(name) :].strip() or '{}'
        else:
            params = 'args'

        entries.append(
            GeneratedEntry(
                name=name,
                params=params,
                documentation=_summarize_description(desc_html),
            )
        )

    return tuple(entries)


def render_generated_block(
    command: str,
    entries: tuple[GeneratedEntry, ...],
    version_label: str,
) -> list[str]:
    lines = [f'{_GENERATED_BEGIN_PREFIX}{command} (Tcl {version_label})', '']

    for entry in entries:
        lines.extend(
            textwrap.wrap(
                entry.documentation,
                width=78,
                initial_indent='# ',
                subsequent_indent='# ',
            )
        )
        name_word = f'{{{entry.name}}}' if ' ' in entry.name else entry.name
        lines.append(f'meta command {name_word} {_tcl_word(entry.params)}')
        lines.append('')

    lines.append(f'{_GENERATED_END_PREFIX}{command}')
    lines.append('')
    return lines


def load_doc_page(command: str, doc_root: str) -> str:
    if '://' in doc_root:
        url = doc_root.rstrip('/') + f'/{command}.htm'
        request = urllib.request.Request(url, headers=_REQUEST_HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode('utf-8', 'replace')
        except urllib.error.URLError as error:
            raise RuntimeError(f'Failed to fetch Tcl docs for `{command}` from {url}.') from error

    path = Path(doc_root) / f'{command}.htm'
    try:
        return path.read_text(encoding='utf-8')
    except OSError as error:
        raise RuntimeError(f'Failed to read Tcl docs for `{command}` from {path}.') from error


def _ensure_generator_note(source_text: str) -> str:
    if _GENERATOR_NOTE in source_text:
        return source_text

    lines = source_text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith('# Descriptions are adapted from the Tcl '):
            lines.insert(index, _GENERATOR_NOTE)
            break
    else:
        lines.insert(0, _GENERATOR_NOTE)

    return '\n'.join(lines).rstrip() + '\n'


def _update_description_line(source_text: str, version_label: str) -> str:
    replacement = f'# Descriptions are adapted from the Tcl {version_label} command manual.'
    if _DESCRIPTION_LINE_PATTERN.search(source_text):
        return _DESCRIPTION_LINE_PATTERN.sub(replacement, source_text, count=1)
    return source_text.rstrip() + f'\n{replacement}\n'


def _entry_name(head_html: str) -> str | None:
    bold_fragments = re.findall(r'<B>(.*?)</B>', head_html, re.DOTALL)
    if not bold_fragments:
        return None
    if '|' in head_html and len(bold_fragments) > 1:
        bold_fragments = bold_fragments[:1]

    tokens: list[str] = []
    for fragment in bold_fragments:
        for token in re.findall(r'[A-Za-z0-9_:.+-]+', html.unescape(fragment)):
            if token == '--' or token.startswith('-'):
                continue
            tokens.append(token)

    return ' '.join(tokens) if tokens else None


def _strip_heading_text(fragment: str) -> str:
    fragment = re.sub(r'<A [^>]*>', '', fragment)
    fragment = fragment.replace('</A>', '')
    fragment = re.sub(r'<[^>]+>', ' ', fragment)
    text = _normalize_unicode(html.unescape(fragment))
    return re.sub(r'\s+', ' ', text).strip()


def _summarize_description(desc_html: str) -> str:
    desc_html = re.sub(r'<DL[^>]*>.*?</DL>', '', desc_html, flags=re.DOTALL)
    text = _strip_doc_text(desc_html)
    if not text:
        return ''

    sentence_match = re.search(r'(.+?\.(?:[)"])?)(?:$|\s+[A-Z\[])', text)
    if sentence_match is not None:
        return sentence_match.group(1).strip()

    first, separator, _ = text.partition('.')
    if separator:
        return (first + '.').strip()
    return text[:220].rstrip()


def _strip_doc_text(fragment: str) -> str:
    fragment = re.sub(r'<A [^>]*>', '', fragment)
    fragment = fragment.replace('</A>', '')
    fragment = re.sub(r'<[^>]+>', ' ', fragment)
    text = _normalize_unicode(html.unescape(fragment))
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'\s+([.,;:])', r'\1', text)
    text = text.replace('( ', '(').replace(' )', ')')
    return text


def _normalize_unicode(text: str) -> str:
    return (
        text.replace('\xa0', ' ')
        .replace('“', '"')
        .replace('”', '"')
        .replace('’', "'")
        .replace('‘', "'")
    )


def _tcl_word(text: str) -> str:
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return '{}'
    if '{' in text or '}' in text or '"' in text:
        escaped = text.replace('\\', '\\\\').replace('"', '\\"')
        return f'"{escaped}"'
    return f'{{{text}}}'


if __name__ == '__main__':
    raise SystemExit(main())
