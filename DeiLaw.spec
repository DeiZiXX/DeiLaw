# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path(SPECPATH)
ICON_CANDIDATES = [
    ROOT / 'assets' / 'icons' / 'icon.ico',
    ROOT / 'assets' / 'icons' / 'icon256.ico',
    ROOT / 'installer' / 'assets' / 'deilaw_installer.ico',
]
APP_ICON = next((str(p.resolve()) for p in ICON_CANDIDATES if p.is_file()), None)
if APP_ICON is None:
    raise FileNotFoundError('DeiLaw icon missing: installer/assets/deilaw_installer.ico. Restore installer/assets before building.')
VERSION_FILE = str((ROOT / 'installer' / 'version_info.txt').resolve())
if not Path(VERSION_FILE).is_file():
    raise FileNotFoundError('Windows version metadata missing: installer/version_info.txt')

datas = []
if (ROOT / 'assets').exists():
    datas.append((str(ROOT / 'assets'), 'assets'))

hiddenimports = [
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
]

a = Analysis(
    ['main.py'],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DeiLaw',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=APP_ICON,
    version=VERSION_FILE,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DeiLaw',
)
