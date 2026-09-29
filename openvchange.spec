# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for OpenVChange.

Build with:  poetry run pyinstaller openvchange.spec
Output:      dist/OpenVChange-<version>.exe  (single-file build)

The version is read from pyproject.toml, so the name of the output and the
details Windows shows for the file always match the package version.
"""

import re
import tomllib
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

block_cipher = None

APP_NAME = "OpenVChange"
DESCRIPTION = "OpenVChange - virtual audio router and voice changer"
ICON = "openvchange/assets/icon.ico"
with open(Path(SPECPATH) / "pyproject.toml", "rb") as f:
    VERSION = tomllib.load(f)["tool"]["poetry"]["version"]

# What Windows shows under Properties > Details. It wants the version as four numbers,
# so anything after the third, such as a pre-release tag, is left out of those.
_numbers = [int(n) for n in re.findall(r"\d+", VERSION.split("-")[0].split("+")[0])][:3]
_numbers += [0] * (4 - len(_numbers))
VERSION_INFO = VSVersionInfo(
    ffi=FixedFileInfo(filevers=tuple(_numbers), prodvers=tuple(_numbers)),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",  # US English, Unicode
                    [
                        StringStruct("ProductName", APP_NAME),
                        StringStruct("FileDescription", DESCRIPTION),
                        StringStruct("FileVersion", VERSION),
                        StringStruct("ProductVersion", VERSION),
                        StringStruct("InternalName", APP_NAME),
                        StringStruct("OriginalFilename", f"{APP_NAME}-{VERSION}.exe"),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

# Qt modules the app never imports; excluding them keeps the bundle small.
qt_excludes = [
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtGraphs",
    "PySide6.QtHelp",
    "PySide6.QtLocation",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNetwork",
    "PySide6.QtNetworkAuth",
    "PySide6.QtNfc",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtPrintSupport",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialBus",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSql",
    "PySide6.QtStateMachine",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
    "PySide6.QtXml",
]

a = Analysis(
    ["openvchange/__main__.py"],
    pathex=["."],
    binaries=[],
    # Unpacked next to the package, where openvchange/resources.py looks for them.
    datas=[("openvchange/assets/*", "openvchange/assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=qt_excludes + ["tkinter", "matplotlib", "IPython", "pytest", "scipy"],
    noarchive=False,
)

# The PySide6 hook drags in Qt libraries this app never loads, via two
# optional plugins: the virtual keyboard (needs QtQuick/QtQml) and the PDF
# image format (needs Qt6Pdf). opengl32sw is a software OpenGL fallback that
# a plain QtWidgets app does not use. Dropping them saves ~40 MB.
_unused_qt = re.compile(
    r"(Qt6Quick|Qt6Qml|Qt6Pdf|Qt6VirtualKeyboard|Qt6OpenGL|Qt6Network|Qt6Svg"
    r"|opengl32sw|qtvirtualkeyboardplugin|qpdf\.dll|qsvg|qsvgicon|Qt6Labs)",
    re.IGNORECASE,
)
a.binaries = [b for b in a.binaries if not _unused_qt.search(b[0])]
a.datas = [d for d in a.datas if not _unused_qt.search(d[0])]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=f"{APP_NAME}-{VERSION}",
    icon=ICON,
    version=VERSION_INFO,
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
)
