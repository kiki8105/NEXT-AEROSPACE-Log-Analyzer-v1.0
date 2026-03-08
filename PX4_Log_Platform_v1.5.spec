# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

SPEC_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = SPEC_DIR.parent
MAIN_SCRIPT = SPEC_DIR / "src" / "gui" / "main_window.py"
ICON_MAIN = WORKSPACE_ROOT / "Logo_main.ico"
ICON_UI = WORKSPACE_ROOT / "Logo.ico"

a = Analysis(
    [str(MAIN_SCRIPT)],
    pathex=[str(SPEC_DIR)],
    binaries=[],
    datas=[
        (str(ICON_MAIN), "."),
        (str(ICON_UI), "."),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PX4_Log_Platform",
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
    icon=[str(ICON_MAIN)],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="PX4_Log_Platform",
)

