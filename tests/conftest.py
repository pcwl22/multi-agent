import uuid
from pathlib import Path


def pytest_configure(config):
    if config.option.basetemp is None:
        root = Path(__file__).parents[1] / ".repopilot" / "test-temp"
        root.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(root / uuid.uuid4().hex)
