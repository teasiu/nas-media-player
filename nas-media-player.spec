# nas-media-player.spec
# 使用方法：pyinstaller nas-media-player.spec

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['nas-media-player.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # uvicorn 核心
        'uvicorn',
        'uvicorn.main',
        'uvicorn.config',
        'uvicorn.server',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.http.httptools_impl',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.protocols.websockets.wsproto_impl',
        'uvicorn.lifespan',
        'uvicorn.lifespan.off',
        'uvicorn.lifespan.on',
        'uvicorn.logging',
        'uvicorn.middleware',
        'uvicorn.middleware.asgi2',
        'uvicorn.middleware.message_logger',
        'uvicorn.middleware.proxy_headers',

        # fastapi / starlette
        'fastapi',
        'fastapi.routing',
        'fastapi.middleware',
        'fastapi.middleware.cors',
        'fastapi.staticfiles',
        'fastapi.responses',
        'starlette',
        'starlette.routing',
        'starlette.middleware',
        'starlette.middleware.cors',
        'starlette.staticfiles',
        'starlette.responses',
        'starlette.background',
        'starlette.concurrency',
        'starlette.datastructures',
        'starlette.exceptions',
        'starlette.formparsers',
        'starlette.requests',
        'starlette.types',
        'starlette.websockets',

        # HTTP 解析库（uvicorn 可选依赖，打包时都带上）
        'h11',
        'httptools',
        'anyio',
        'anyio._backends._asyncio',
        'anyio._backends._trio',
        'sniffio',

        # aiofiles
        'aiofiles',
        'aiofiles.os',
        'aiofiles.threadpool',

        # pydantic（fastapi 依赖）
        'pydantic',
        'pydantic.v1',
        'pydantic_core',

        # 标准库补充
        'multipart',
        'python_multipart',
        'email.mime.multipart',
        'email.mime.text',

        # 编码/哈希
        'hashlib',
        'hmac',

        # 其他
        'click',
        'typing_extensions',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不需要的大型库，减小体积
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'PIL',
        'scipy',
        'IPython',
        'jupyter',
        'notebook',
        'test',
        'unittest',
    ],
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
    name='nas-media-player',  # 输出的二进制名
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,               # strip 调试符号，减小体积
    upx=True,                 # 若系统有 upx 则进一步压缩
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
