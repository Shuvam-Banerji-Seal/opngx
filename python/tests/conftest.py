"""Shared fixtures for the opngx pytest suite."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def native_available():
    from opngx._engine import load_library

    return load_library() is not None


@pytest.fixture(scope="session")
def fixture_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("fixture")
    subprocess.run(
        [sys.executable, str(REPO / "tests" / "gen_fixture.py"), str(out)],
        check=True,
        capture_output=True,
    )
    return out
