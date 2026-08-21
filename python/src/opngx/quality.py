"""Quality modes and LUT construction.

The vendor display transform (verified pixel-exact against reference exports):
    out = clamp(round_half_up((v + brightness) * (1 + contrast/50)), 0, 255)
Optional gamma applied afterwards on the normalized range.
RAW mode bypasses the transform entirely (identity), preserving sensor data
that the vendor export clips at the top of range.
"""

from __future__ import annotations

from enum import Enum

import numpy as np


class QualityMode(str, Enum):
    REFERENCE = "reference"  # replicate vendor display transform exactly
    RAW = "raw"  # identity — maximum fidelity, no clipping
    CUSTOM = "custom"  # user brightness/contrast/gamma


def build_lut(brightness: float, contrast: float, gamma: float = 1.0) -> np.ndarray:
    """256-entry uint8 LUT implementing the verified transform."""
    mul = 1.0 + contrast / 50.0
    lut = np.clip(
        np.floor((np.arange(256, dtype=np.float64) + brightness) * mul + 0.5),
        0.0,
        255.0,
    )
    if gamma != 1.0 and gamma > 0:
        lut = np.floor(255.0 * np.power(lut / 255.0, 1.0 / gamma) + 0.5)
    return lut.astype(np.uint8)
