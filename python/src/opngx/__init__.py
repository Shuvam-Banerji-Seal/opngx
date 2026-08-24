"""opngx — ultra-fast Optronis .bin → PNG extraction.

Public API:
    probe(bin_path)                    -> FootageMetadata
    extract(bin_path, out_dir, ...)    -> ExtractStats
    verify(ref_dir, out_dir, ...)      -> VerifyReport
    engine_backend()                   -> str
"""

from .footage import FootageMetadata, probe, read_timestamps
from .timing import analyze_timestamps
from .extractor import ExtractStats, Extractor, extract
from .quality import QualityMode
from .verify import VerifyReport, verify, verify_against_bin
from .video import render_video, read_frame_gray, ffmpeg_available

__version__ = "1.5.3"


def engine_diagnostics() -> list[str]:
    """Why the native engine did/didn't load — shown in the UI log."""
    from ._engine import engine_diagnostics as _d

    return _d()


def engine_backend() -> str:
    """'native (path)' when the C engine is available, else 'python-fallback'."""
    from ._engine import library_path

    lp = library_path()
    return f"native ({lp})" if lp else "python-fallback"


def detect_gpus() -> list[str]:
    """GPU descriptions via the native engine's portable detection."""
    from ._engine import detect_gpus as _d

    return _d()


__all__ = [
    "FootageMetadata",
    "probe",
    "read_timestamps",
    "ExtractStats",
    "Extractor",
    "extract",
    "QualityMode",
    "VerifyReport",
    "verify",
    "verify_against_bin",
    "engine_backend",
    "__version__",
]
