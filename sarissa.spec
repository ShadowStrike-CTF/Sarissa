# sarissa.spec
# PyInstaller spec for Sarissa — ShadowStrike CTF dashboard
# Build: pyinstaller sarissa.spec --clean   (run locally on Windows)

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

a = Analysis(
    ['src/sarissa/__main__.py'],
    pathex=['src'],  # package lives under src/ — '.' would not resolve `import sarissa`
    binaries=[],
    datas=[
        # index.html — served by main.static_dir(), which reads sys._MEIPASS/sarissa/static when frozen.
        ('src/sarissa/static', 'sarissa/static'),
    ],
    hiddenimports=[
        # uvicorn internals not auto-detected by PyInstaller
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        # anyio backend
        'anyio._backends._asyncio',
        # python-magic (libmagic wrapper)
        'magic',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='sarissa',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # UPX off — AV false positives on CTF machines
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,       # no CMD window; windowed exe
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon= omitted — no icon required
    onefile=True,        # single .exe for easy distribution
)
