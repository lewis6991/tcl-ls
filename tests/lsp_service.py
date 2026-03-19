from __future__ import annotations

from lsprotocol import types

from tcl_lsp.common import Diagnostic, HoverInfo
from tcl_lsp.lsp import LanguageServer
from tcl_lsp.lsp.features.hover import hover
from tcl_lsp.lsp.features.navigation import definition, references
from tcl_lsp.lsp.features.rename import rename
from tcl_lsp.lsp.state import IndexingProgressCallback, RenameEdit


class LanguageService:
    def __init__(self) -> None:
        self.server = LanguageServer()

    def open_document(
        self,
        uri: str,
        text: str,
        version: int,
        *,
        progress: IndexingProgressCallback | None = None,
    ) -> tuple[Diagnostic, ...]:
        return self.server.open_document(uri, text, version, progress=progress)

    def change_document(self, uri: str, text: str, version: int) -> tuple[Diagnostic, ...]:
        return self.server.change_document(uri, text, version)

    def close_document(self, uri: str) -> None:
        self.server.close_document(uri)

    def definition(self, uri: str, line: int, character: int) -> tuple[types.Location, ...]:
        return definition(
            self.server.documents,
            workspace_index=self.server.workspace_index,
            metadata_registry=self.server.metadata_registry,
            uri=uri,
            line=line,
            character=character,
        )

    def references(
        self,
        uri: str,
        line: int,
        character: int,
        include_declaration: bool = True,
    ) -> tuple[types.Location, ...]:
        return references(
            self.server.documents,
            metadata_registry=self.server.metadata_registry,
            uri=uri,
            line=line,
            character=character,
            include_declaration=include_declaration,
        )

    def rename(
        self,
        uri: str,
        line: int,
        character: int,
        new_name: str,
    ) -> dict[str, tuple[RenameEdit, ...]] | None:
        return rename(
            self.server.documents,
            uri=uri,
            line=line,
            character=character,
            new_name=new_name,
        )

    def hover(self, uri: str, line: int, character: int) -> HoverInfo | None:
        return hover(self.server.documents, uri=uri, line=line, character=character)
