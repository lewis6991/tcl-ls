# vim: set filetype=python

from pathlib import Path
from typing import TYPE_CHECKING

from PyInstaller.utils.hooks import collect_data_files

if TYPE_CHECKING:
    from PyInstaller.building.api import COLLECT, EXE, PYZ
    from PyInstaller.building.build_main import Analysis

    SPECPATH = str(Path(__file__).parent)

ROOT_DIR = Path(SPECPATH).resolve()
SRC_DIR = ROOT_DIR / 'src'
META_DIR = ROOT_DIR / 'meta'

meta_datas = [
    (
        str(path),
        str(Path('tcl_lsp/meta') / path.relative_to(META_DIR).parent),
    )
    for path in sorted(META_DIR.rglob('*'))
    if path.is_file()
]

analysis = Analysis(
    [str(SRC_DIR / 'tcl_lsp' / '__main__.py')],
    pathex=[str(SRC_DIR)],
    binaries=[],
    datas=[*collect_data_files('tcl_lsp'), *meta_datas],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name='tcl-ls',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='tcl-ls',
)
