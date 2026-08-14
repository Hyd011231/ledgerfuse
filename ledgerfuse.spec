# -*- mode: python ; coding: utf-8 -*-
# 打包：pyinstaller ledgerfuse.spec --noconfirm
# 前提：frontend/dist 已构建；packaging/icon.icns|ico 已生成（可选，缺了用默认图标）
import sys
from pathlib import Path

is_mac = sys.platform == "darwin"
is_win = sys.platform == "win32"

root = Path(SPECPATH)
icon_icns = root / "packaging" / "icon.icns"
icon_ico = root / "packaging" / "icon.ico"

a = Analysis(
    ["backend/desktop.py"],
    pathex=["backend"],
    datas=[
        ("frontend/dist", "dist"),
        ("backend/app/seed", "app/seed"),
    ],
    hiddenimports=[
        "app", "app.main",
        "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
        "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl", "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto", "uvicorn.lifespan", "uvicorn.lifespan.on",
    ],
    excludes=["tkinter"],
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LedgerFuse",
    console=False,
    icon=str(icon_ico) if (is_win and icon_ico.exists()) else None,
)

coll = COLLECT(exe, a.binaries, a.datas, name="LedgerFuse")

if is_mac:
    app = BUNDLE(
        coll,
        name="LedgerFuse.app",
        icon=str(icon_icns) if icon_icns.exists() else None,
        bundle_identifier="app.ledgerfuse",
        info_plist={
            "CFBundleName": "LedgerFuse",
            "CFBundleDisplayName": "合账",
            "CFBundleShortVersionString": "1.0.0",
            "NSHighResolutionCapable": True,
        },
    )
