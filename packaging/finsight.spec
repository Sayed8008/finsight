# PyInstaller build specification for the bundled FinSight application.
#
#     .venv/bin/pyinstaller packaging/finsight.spec --noconfirm
#
# Produces `dist/FinSight/` — a folder containing one executable and its
# libraries. A folder rather than `--onefile`: a single file has to unpack
# 200-odd megabytes to a temporary directory on *every* launch, which turns a
# double-click into a visible wait. The folder starts immediately, and zipping
# it for sharing is one command.
#
# What is not bundled, deliberately:
#
#   * MySQL. The analytics layer depends on its date functions and GROUP BY
#     semantics (ADR-005), so it is a real dependency rather than a packaging
#     oversight.
#   * `.env`. It holds a SECRET_KEY and a database password. Bundling one would
#     ship the developer's credentials to everybody who received a copy.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

PROJECT = Path(SPECPATH).parent
RESOURCES = PROJECT / "frontend" / "client" / "resources"
WINDOWS = sys.platform == "win32"

# Windows executables carry a `.ico` and PyInstaller refuses anything else on
# that platform; elsewhere the SVG the application itself uses is fine. The
# `.ico` is generated from that same SVG by `packaging/make_icon.py`, so the
# two cannot drift.
ICON = RESOURCES / ("finsight.ico" if WINDOWS else "finsight.svg")
if not ICON.is_file():
    raise SystemExit(
        f"Missing icon: {ICON}\n"
        "On Windows, generate it first:  python packaging/make_icon.py"
    )

# The name Windows expects on an executable. PyInstaller adds it on Windows
# whether or not it is written here, but being explicit means the zip contents
# are predictable from reading this file.
EXE_NAME = "FinSight"

# The QSS and the icons are read from disk at runtime, so they have to travel
# with the bundle rather than being imported.
datas = [
    (str(PROJECT / "frontend" / "client" / "resources"), "client/resources"),
]

# Alembic's migration scripts are loaded by path, not imported, so PyInstaller
# cannot see them by following imports.
alembic_dir = PROJECT / "backend" / "alembic"
if alembic_dir.is_dir():
    datas.append((str(alembic_dir), "alembic"))

hiddenimports = [
    # Chosen by name at runtime from a configuration string, so nothing
    # imports them anywhere PyInstaller can follow.
    "pymysql",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    # Pydantic and SQLAlchemy resolve plenty of their own machinery lazily.
    *collect_submodules("pydantic"),
    *collect_submodules("passlib"),
]

a = Analysis(
    [str(PROJECT / "packaging" / "finsight_app.py")],
    pathex=[str(PROJECT / "backend"), str(PROJECT / "frontend")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Qt ships a great deal this application never touches. Excluding the
    # largest of them is the difference between a share people will download
    # and one they will not.
    excludes=[
        "tkinter",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.Qt3DCore",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtMultimedia",
        "PySide6.QtBluetooth",
        "PySide6.QtDesigner",
        "matplotlib",
        "pytest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=EXE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # a desktop application, not a terminal one
    icon=str(ICON),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="FinSight",
)
