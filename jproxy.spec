# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['/home/jiao/123456/tmp/jproxy_cli.py'],
    pathex=[],
    binaries=[],
    datas=[('/home/jiao/123456/tmp/proxy.py', '.'), ('/home/jiao/123456/tmp/start.py', '.'), ('/home/jiao/123456/tmp/model_manager.py', '.'), ('/home/jiao/123456/tmp/translator.py', '.')],
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
    name='jproxy',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
