from __future__ import annotations

import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_collection_modifyitems(config, items):
    skip_win = pytest.mark.skip(reason="requires a Windows desktop session")
    for item in items:
        if "win32" in item.keywords and sys.platform != "win32":
            item.add_marker(skip_win)


@pytest.fixture
def fixture_url() -> str:
    return (FIXTURES / "page.html").resolve().as_uri()
