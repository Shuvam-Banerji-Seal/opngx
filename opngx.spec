# PyInstaller spec — opngx studio for Windows.
# Built inside CI's windows job AFTER the native engine is compiled:
#   pyinstaller --noconfirm opngx.spec
# Expects build-win/libopngx.dll and dist/opngx-engine.exe to exist.
import os
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
root = os.path.abspath(".")
dll = os.path.join(root, "build-win", "libopngx.dll")

hidden = collect_submodules("opngx") + [
    "opngx.ui.app", "opngx.ui.theme", "opngx.ui.widgets",
    "opngx.ui.qt_app", "opngx.video",
]

a = Analysis(
    ["python/opngx_ui_entry.py"],
    pathex=[os.path.join(root, "python")],
    binaries=[(dll, ".")] if os.path.exists(dll) else [],
    datas=[
        (os.path.join(root, "README.md"), "docs"),
        (os.path.join(root, "docs", "FORMAT.md"), "docs"),
        (os.path.join(root, "docs", "BENCHMARKS.md"), "docs"),
    ],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter.test", "test", "unittest"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name="opngx-studio",
    console=False,               # windowed app: no console flash
    upx=False,
    icon=None,
)
