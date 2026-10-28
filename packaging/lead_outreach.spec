# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for "Lead Outreach" (one-folder, no console window).
#
# Build (from the repository root):
#   python packaging/make_icon.py
#   pyinstaller packaging/lead_outreach.spec --noconfirm --clean
# Output: dist/Lead Outreach/Lead Outreach.exe  (+ _internal/)
#
# Debugging tip: set OUTREACH_CONSOLE=1 before building to get a console window.

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parent          # repository root
PKG = ROOT / "packaging"
APP = ROOT / "app"
NAME = "Lead Outreach"

if not (APP / "__main__.py").is_file():
    raise SystemExit(f"app/__main__.py not found under {ROOT}: is the backend in place?")
if not (APP / "web" / "index.html").is_file():
    raise SystemExit("app/web/index.html not found: is the frontend in place?")

# --- Data files ------------------------------------------------------------
# Every non-Python file inside app/ (web UI, engine resources such as
# useragents.txt, area presets, templates...) keeps its relative path, so
# resource_path("app/web/index.html") etc. works under sys._MEIPASS.
datas = []
for f in APP.rglob("*"):
    if not f.is_file():
        continue
    if "__pycache__" in f.parts or f.suffix in (".py", ".pyc", ".pyo"):
        continue
    if f.name in (".DS_Store", "Thumbs.db"):
        continue
    datas.append((str(f), str(f.parent.relative_to(ROOT))))

# Selenium ships selenium-manager(.exe) and JS atoms as package data.
datas += collect_data_files("selenium")
datas += collect_data_files("certifi")
for dist in ("selenium", "flask", "waitress"):
    try:
        datas += copy_metadata(dist)
    except Exception:
        pass

# --- Hidden imports ----------------------------------------------------------
# The launcher imports the backend dynamically, so collect it explicitly.
hiddenimports = collect_submodules("app")
hiddenimports += collect_submodules("waitress")
hiddenimports += ["selenium.webdriver.chrome.webdriver", "selenium.webdriver.common.selenium_manager"]

# --- Icon ----------------------------------------------------------------------
icon = PKG / "build" / "app.ico"
icon = str(icon) if icon.is_file() else None

console = os.environ.get("OUTREACH_CONSOLE", "") == "1"

a = Analysis(
    [str(PKG / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "IPython", "matplotlib", "numpy.tests", "PyQt5", "PySide6"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # UPX-packed exes trigger more antivirus false positives
    console=console,     # windowed: no black terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=NAME,
)
