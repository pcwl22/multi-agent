import hashlib
import json
from pathlib import Path


def test_intentional_bug_fixture_matches_immutable_manifest():
    root = Path(__file__).parents[2] / "test_fixtures"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for relative, expected in manifest["files"].items():
        assert hashlib.sha256((root / "repair_repository" / relative).read_bytes()).hexdigest() == expected
    assert 'status_code=500, detail="Token expired"' in (
        root / "repair_repository/auth.py").read_text(encoding="utf-8")
