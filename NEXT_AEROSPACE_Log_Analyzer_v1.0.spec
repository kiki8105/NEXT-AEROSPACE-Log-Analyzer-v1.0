# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src\\gui\\main_window.py'],
    pathex=[],
    binaries=[],
    datas=[('c:/Users/rldnd/Desktop/로그분석툴 개발/Logo_main.ico', '.'), ('c:/Users/rldnd/Desktop/로그분석툴 개발/Logo.ico', '.')],
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
    a.binaries,
    a.datas,
    [],
    name='PX4_Log_Platform_v1.6',
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
    icon=['c:\\Users\\rldnd\\Desktop\\로그분석툴 개발\\Logo_main.ico'],
)
