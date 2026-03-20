from __future__ import annotations

from lsprotocol import types

from tcl_lsp.analysis import WorkspaceIndex
from tcl_lsp.common import lsp_range
from tcl_lsp.lsp.state import ManagedDocument


def document_links(
    document: ManagedDocument,
    *,
    workspace_index: WorkspaceIndex,
) -> tuple[types.DocumentLink, ...]:
    links: list[types.DocumentLink] = []
    seen: set[tuple[int, int, int, int, str]] = set()

    for directive in document.facts.source_directives:
        _add_document_link(
            links,
            seen,
            types.DocumentLink(
                range=lsp_range(directive.span),
                target=directive.target_uri,
                tooltip='Open sourced file.',
            ),
        )

    for package_require in document.facts.package_requires:
        target_uri = _package_target_uri(workspace_index, package_require.name)
        if target_uri is None:
            continue
        _add_document_link(
            links,
            seen,
            types.DocumentLink(
                range=lsp_range(package_require.span),
                target=target_uri,
                tooltip=f'Open package source for `{package_require.name}`.',
            ),
        )

    return tuple(links)


def _package_target_uri(workspace_index: WorkspaceIndex, package_name: str) -> str | None:
    target_uris = tuple(
        dict.fromkeys(
            (
                *workspace_index.package_source_uris(package_name),
                *(
                    package.uri
                    for package in workspace_index.provided_packages_for_name(package_name)
                ),
            )
        )
    )
    if len(target_uris) != 1:
        return None
    return target_uris[0]


def _add_document_link(
    links: list[types.DocumentLink],
    seen: set[tuple[int, int, int, int, str]],
    link: types.DocumentLink,
) -> None:
    if link.target is None:
        return

    key = (
        link.range.start.line,
        link.range.start.character,
        link.range.end.line,
        link.range.end.character,
        link.target,
    )
    if key in seen:
        return
    seen.add(key)
    links.append(link)
