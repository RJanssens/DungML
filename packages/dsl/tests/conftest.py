from pathlib import Path

import pytest

SAMPLES_DIR = Path(__file__).resolve().parents[3] / "samples"


@pytest.fixture
def crypt_source() -> str:
    return (SAMPLES_DIR / "crypt.dmap").read_text(encoding="utf-8")


@pytest.fixture
def cottage_source() -> str:
    return (SAMPLES_DIR / "cottage.dmap").read_text(encoding="utf-8")


@pytest.fixture
def quickstart_source() -> str:
    return (SAMPLES_DIR / "quickstart.dmap").read_text(encoding="utf-8")
