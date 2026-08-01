from __future__ import annotations

from pathlib import Path

from tcl_lsp.project.paths import source_id_to_path

_ASSET_DIR = Path(__file__).resolve().parent / 'assets' / 'json'
_EXTENSION_TO_PACKAGE = {
    '.exp': 'expect',
    '.xdc': 'vivado',
    '.xsct': 'xsct',
}
_SHEBANG_MARKERS = (
    ('expect', 'expect'),
    ('vivado', 'vivado'),
    ('xsct', 'xsct'),
)
_JSON_PATHS_BY_PACKAGE = {
    package_name: _ASSET_DIR / f'{package_name}.json'
    for package_name in ('expect', 'vivado', 'xsct')
}


def contextual_builtin_json_path(package_name: str) -> Path | None:
    return _JSON_PATHS_BY_PACKAGE.get(package_name)


def contextual_builtin_packages(
    uri: str,
    *,
    text: str | None = None,
    shebang: str | None = None,
) -> frozenset[str]:
    package_name = contextual_builtin_package(uri, text=text, shebang=shebang)
    if package_name is None:
        return frozenset()
    return frozenset({package_name})


def contextual_builtin_package(
    uri: str,
    *,
    text: str | None = None,
    shebang: str | None = None,
) -> str | None:
    shebang_line = _shebang_line(text=text, shebang=shebang)
    if shebang_line is not None:
        for marker, package_name in _SHEBANG_MARKERS:
            if marker in shebang_line:
                return package_name

    source_path = source_id_to_path(uri)
    if source_path is None:
        return None
    return _EXTENSION_TO_PACKAGE.get(source_path.suffix.casefold())


def _shebang_line(*, text: str | None, shebang: str | None) -> str | None:
    candidate = shebang
    if candidate is None and text:
        candidate = text.splitlines()[0]
    if candidate is None or not candidate.startswith('#!'):
        return None
    return candidate.casefold()
