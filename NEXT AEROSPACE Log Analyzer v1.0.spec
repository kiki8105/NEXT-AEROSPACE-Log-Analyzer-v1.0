# -*- mode: python ; coding: utf-8 -*-

import os
from PyInstaller.building.datastruct import TOC

MSVCR90_PATH = r"C:\Windows\WinSxS\amd64_microsoft.vc90.crt_1fc8b3b9a1e18e3b_9.0.30729.9635_none_08e2c157a83ed5da\msvcr90.dll"
MSVCR90_DIR = os.path.dirname(MSVCR90_PATH)

if os.path.isdir(MSVCR90_DIR):
    _path_parts = os.environ.get("PATH", "").split(os.pathsep)
    if MSVCR90_DIR not in _path_parts:
        os.environ["PATH"] = os.pathsep.join([MSVCR90_DIR] + _path_parts)

a = Analysis(
    ['src\\gui\\main_window.py'],
    pathex=[],
    binaries=[(MSVCR90_PATH, '.')],
    datas=[('Logo_main.ico', '.'), ('Logo.ico', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['OpenGL.DLLS'],
    noarchive=False,
    optimize=0,
)

# Drop legacy OpenGL VC9 DLLs that trigger unresolved MSVCR90 warnings
# and are not required for PySide6/pyqtgraph OpenGL rendering.
_legacy_vc9 = (
    'gle64.vc9.dll',
    'gle32.vc9.dll',
    'freeglut32.vc9.dll',
    'freeglut64.vc9.dll',
)
a.binaries = TOC(
    entry
    for entry in a.binaries
    if not any(str(entry[0]).lower().endswith(name) for name in _legacy_vc9)
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='NEXT AEROSPACE Log Analyzer v1.0',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['Logo_main.ico'],
)
