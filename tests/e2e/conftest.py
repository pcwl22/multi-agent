"""Make disposable test repositories readable by the non-root Docker user."""

import os
from pathlib import Path

import pytest


@pytest.fixture
def tmp_path(tmp_path: Path) -> Path:
    # pytest creates this directory with mode 0700 on POSIX. Mounting it directly
    # as /workspace preserves that mode, so uid 65534 cannot even start pytest.
    # Only adjust this fixture's fresh directory; production repositories retain
    # their original permissions and Docker continues to mount them read-only.
    if os.name != "nt":
        tmp_path.chmod(0o755)
    return tmp_path
