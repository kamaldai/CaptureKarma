from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

# Keep pytest's temp root inside the repo. The default %TEMP%\pytest-of-<user> directory on this
# machine has a broken ACL (needs admin to remove), which makes every tmp_path fixture fail.
_TMP_ROOT = Path(__file__).resolve().parent.parent / ".pytest_tmp"
_TMP_ROOT.mkdir(exist_ok=True)
os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", str(_TMP_ROOT))


def pytest_collection_modifyitems(config, items):
    skip_win = pytest.mark.skip(reason="requires a Windows desktop session")
    for item in items:
        if "win32" in item.keywords and sys.platform != "win32":
            item.add_marker(skip_win)


@pytest.fixture
def fixture_url() -> str:
    return (FIXTURES / "page.html").resolve().as_uri()
