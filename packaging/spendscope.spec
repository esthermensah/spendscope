# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

project_root = Path(SPECPATH).parent
source_root = project_root / "src"
app_icon = project_root / "assets" / "spendscope-icon.png"
data_files = [
    (
        str(source_root / "spendscope" / "database" / "migrations"),
        "spendscope/database/migrations",
    ),
]
google_client = source_root / "spendscope" / "reporting" / "google_oauth_client.json"
if google_client.is_file():
    data_files.append((str(google_client), "spendscope/reporting"))

analysis = Analysis(
    [str(project_root / "packaging" / "desktop_entry.py")],
    pathex=[str(source_root)],
    binaries=[],
    datas=data_files,
    hiddenimports=collect_submodules("keyring.backends"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "coverage",
        "hypothesis",
        "mypy",
        "pytest",
        "ruff",
        "tkinter",
        "PySide6.QtQml",
        "PySide6.QtQuick",
    ],
    noarchive=False,
    optimize=1,
)

# google-api-python-client ships static discovery documents for every Google API.
# SpendScope only talks to Sheets and Drive, so retaining the complete catalog
# adds roughly 100 MB to the desktop bundle without adding functionality.
discovery_documents = "googleapiclient/discovery_cache/documents/"
analysis.datas = [
    entry
    for entry in analysis.datas
    if not entry[0].startswith(discovery_documents)
    or entry[0]
    in {
        f"{discovery_documents}drive.v3.json",
        f"{discovery_documents}sheets.v4.json",
    }
]

python_archive = PYZ(analysis.pure)

executable = EXE(
    python_archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="SpendScope",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(app_icon),
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="SpendScope",
)

if sys.platform == "darwin":
    application = BUNDLE(
        collection,
        name="SpendScope.app",
        bundle_identifier="org.spendscope.desktop",
        version="0.1.0",
        icon=str(app_icon),
        info_plist={
            "CFBundleDisplayName": "SpendScope",
            "CFBundleName": "SpendScope",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "2",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
        },
    )
