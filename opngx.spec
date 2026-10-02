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
    "opngx.ui.qt_app", "opngx.ui.batch", "opngx.ui.frameview", "opngx.video",
    "opngx.ui.scaling", "opngx.ui.analysis_ui",
    # analysis modules (v1.10): built-ins are imported by NAME at runtime,
    # which PyInstaller's static analysis cannot see
    "opngx.analysis", "opngx.analysis.base", "opngx.analysis.registry",
    "opngx.analysis.runner", "opngx.analysis.result", "opngx.analysis.stats",
    "opngx.analysis.builtin", "opngx.analysis.builtin.motion_tracking",
    "opngx.analysis.builtin.luminosity", "opngx.analysis.builtin.contrast",
    "opngx.analysis.builtin.brownian", "opngx.analysis.native",
    "opngx.ui.themes", "opngx.ui.editor", "opngx.ui.docs_ui", "opngx.ui.audit", "opngx.docs",
    # v2.1: new modules, formats, tabs, icons, logo
    "opngx.analysis.builtin.focus", "opngx.analysis.builtin.drift", "opngx.analysis.builtin.particles",
    "opngx.analysis.builtin.flicker", "opngx.analysis.builtin.roi_stats",
    "opngx.formats", "opngx._proc", "opngx.ui.icons", "opngx.ui.logo", "opngx.ui.video_ui",
    "opngx.ui.system_ui", "opngx.ui.home_ui",
    # crisp vector icons (QSvgRenderer); the qsvg image plugin is the fallback
    "PySide6.QtSvg",
]

# bundle an ffmpeg binary so Render-video works out of the box
ffbin = None
try:
    import imageio_ffmpeg
    ffbin = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    pass

binaries = [(dll, ".")] if os.path.exists(dll) else []

# bundle the CLI engine so the portable studio is self-contained:
# verify_against_bin / verifybin work with zero external files
engine_exe = os.path.join(root, "build-win", "opngx-engine.exe")
if os.path.exists(engine_exe):
    binaries.append((engine_exe, "."))
if ffbin:
    # bundle under a flat, predictable name so resolve_ffmpeg can find it
    import shutil as _sh
    _dst = os.path.join(root, "_bundled_ffmpeg")
    ext = ".exe" if os.name == "nt" or "win" in ffbin.lower() else ""
    if ext and not _dst.endswith(".exe"):
        _dst += ".exe"
    _sh.copy2(ffbin, _dst)
    binaries.append((_dst, "."))

# v2.0 compact build: imageio_ffmpeg is used at BUILD time only (to find
# the binary above). Bundling the package as well shipped the 88 MB ffmpeg
# twice — resolve_ffmpeg() uses _bundled_ffmpeg first.

# Data files, by glob so a new guide / module / release note can't be
# forgotten again (v2.0 shipped 2 of 3 guides and no release notes).
import glob as _glob

_pkg = os.path.join(root, "python", "src", "opngx")
_datas = [(os.path.join(root, "README.md"), "docs")]
# repo docs: guides + every release note (the Docs tab lists them)
_datas += [(f, "docs") for f in sorted(_glob.glob(os.path.join(root, "docs", "*.md")))]
# package docs, found by the studio next to opngx.docs.__file__
_datas += [(f, "opngx/docs") for f in sorted(_glob.glob(os.path.join(_pkg, "docs", "*.md")))]
# SOURCE of the built-in analysis modules: a frozen module's __file__ is
# <_MEIPASS>/opngx/analysis/builtin/<name>.py, which only exists if it is
# collected. Without it the Editor could not open (or Duplicate) a
# built-in module - clicking it silently did nothing.
_datas += [(f, "opngx/analysis/builtin") for f in sorted(_glob.glob(os.path.join(_pkg, "analysis", "builtin", "*.py")))]
# sample modules + docs copied into the user's empty folders on first start
_datas += [(f, "opngx/analysis/examples") for f in sorted(_glob.glob(os.path.join(_pkg, "analysis", "examples", "*.*")))]
_datas += [(f, "opngx/analysis/examples/docs") for f in sorted(_glob.glob(os.path.join(_pkg, "analysis", "examples", "docs", "*.md")))]
# logo assets shipped with the package (the in-app logo is drawn in code)
_datas += [(f, "opngx/ui/assets") for f in sorted(_glob.glob(os.path.join(_pkg, "ui", "assets", "*.*")))]
if os.path.exists(os.path.join(root, "assets", "logo", "icon.png")):
    _datas.append((os.path.join(root, "assets", "logo", "icon.png"), "assets/logo"))

icon_path = os.path.join(root, "assets", "logo", "icon.ico")
icon_png = os.path.join(root, "assets", "logo", "icon.png")
a = Analysis(
    ["python/opngx_ui_entry.py"],
    # The package uses a src/ layout, so BOTH python/ (the entry script's
    # own directory) and python/src (where opngx actually lives) must be on
    # the path. Listing only python/ makes every `opngx.*` hidden import
    # fail with "not found" whenever the build machine has no editable
    # install of the package — which is exactly the case for a clean
    # Windows/Wine builder.
    pathex=[
        os.path.join(root, "python"),
        os.path.join(root, "python", "src"),
    ],
    binaries=binaries,
    datas=_datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "_tkinter", "tkinter.test", "test", "unittest", "imageio_ffmpeg",
        # Qt modules the studio never imports (widgets only)
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuick3D",
        "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.Qt3DCore", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtNetwork", "PySide6.QtOpenGL",
        "PySide6.QtOpenGLWidgets", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner",
        "PySide6.QtHelp", "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtLocation",
        "PySide6.QtSerialPort", "PySide6.QtWebSockets", "PySide6.QtRemoteObjects",
        "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech", "PySide6.QtUiTools", "PySide6.QtXml",
    ],
    cipher=block_cipher,
)
# drop binaries nothing loads: the software-OpenGL fallback (widgets never
# need it), Qt Quick/QML/PDF/3D libraries pulled in by plugins, Tcl/Tk (the
# Tk fallback UI is not shipped: PySide6 always is) and PIL's AVIF codec.
_DROP = ("opengl32sw", "qt6quick", "qt6qml", "qt6pdf", "qt6quick3d", "qt6shadertools",
         "qt6virtualkeyboard", "qt6webengine", "qt6designer", "qt6multimedia", "avcodec",
         "avformat", "avutil", "swresample", "swscale", "tcl86", "tk86", "_avif", "qt6network",
         "qt6opengl",
         # plugins whose Qt library is dropped above: they could never load
         # (v2.1 bug hunt - qpdf needs Qt6Pdf, the virtual keyboard and
         # touch plugins need Qt6VirtualKeyboard / Qt6Network)
         "qpdf.dll", "qtvirtualkeyboardplugin", "qtuiotouchplugin", "_imagingtk")


def _keep(entry):
    name = entry[0].replace("\\", "/").lower()
    base = name.rsplit("/", 1)[-1]
    if any(base.startswith(d) or d in base for d in _DROP):
        return False
    if name.startswith(("tcl/", "tk/", "_tcl_data", "_tk_data", "tcl8/")):
        return False
    return True


a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name="opngx-studio",
    console=False,               # windowed app: no console flash
    upx=False,
    icon=icon_path if os.path.exists(icon_path) else None,
)
