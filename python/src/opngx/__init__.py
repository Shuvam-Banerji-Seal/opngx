"""opngx — ultra-fast Optronis .bin → PNG extraction.

Public API:
    probe(bin_path)                    -> FootageMetadata
    extract(bin_path, out_dir, ...)    -> ExtractStats
    verify(ref_dir, out_dir, ...)      -> VerifyReport
    engine_backend()                   -> str
"""

from .footage import FootageMetadata, probe, read_timestamps
from .extractor import ExtractStats, Extractor, extract
from .quality import QualityMode
from .verify import VerifyReport, verify
from .video import render_video, read_frame_gray, ffmpeg_available

__version__ = "1.3.0"


def engine_diagnostics() -> list[str]:
    """Why the native engine did/didn't load — shown in the UI log."""
    from ._engine import engine_diagnostics as _d
    return _d()


def engine_backend() -> str:
    """'native (path)' when the C engine is available, else 'python-fallback'."""
    from ._engine import library_path

    lp = library_path()
    return f"native ({lp})" if lp else "python-fallback"


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
    "engine_backend",
    "__version__",
]
