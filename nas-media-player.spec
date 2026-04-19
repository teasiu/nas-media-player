# nas-media-player.spec

block_cipher = None

a = Analysis(
    ['nas-media-player.py'],
    pathex=[],
    binaries=[],
    datas=[],

    hiddenimports=[
        'uvicorn',
        'fastapi',
        'starlette',
        'pydantic',
        'anyio',
        'aiofiles',
        'python_multipart',
    ],

    hookspath=[],
    runtime_hooks=[],

    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'IPython',
        'jupyter',
        'notebook',
        'test',
        'unittest',
    ],

    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,

    [],
    name='nas-media-player',

    debug=False,

    strip=True,

    upx=False,

    console=True,
)
