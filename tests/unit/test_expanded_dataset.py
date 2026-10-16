import json
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.evaluation.runner import run_evaluation

ROOT = Path(__file__).parents[2] / "app/evaluation/expanded"


def test_expanded_corpus_is_separate_and_has_cross_file_case():
    cases = json.loads((ROOT / "dataset.json").read_text(encoding="utf-8"))
    assert len(cases) == len({c["id"] for c in cases}) == 10
    references = json.loads((ROOT / "references.json").read_text(encoding="utf-8"))
    assert any(len(edits) > 1 for edits in references.values())
    for case in cases:
        source = ROOT / case["repository"]
        assert (source / "tests/test_contract.py").exists()
        assert (source / "legacy_examples.py").exists()
        assert not (source / "references.json").exists()
        assert not (source / case["acceptance"]).exists()


@pytest.mark.parametrize(
    "case_id,acceptance", [("../outside", "test.py"), ("safe", "../../escape.py")]
)
def test_dataset_rejects_escaping_paths_before_starting_models(tmp_path, case_id, acceptance):
    dataset = tmp_path / "dataset.json"
    dataset.write_text(
        json.dumps([{"id": case_id, "issue": "something broken", "acceptance": acceptance}]),
        encoding="utf-8",
    )
    # The escape target exists, so rejection must use containment, not missing-file errors.
    outside = tmp_path.parent / "escape.py"
    outside.write_text("def test_x(): pass\n", encoding="utf-8")
    (tmp_path / "acceptance").mkdir()
    with pytest.raises(ValueError, match="path-safe|inside the dataset"):
        run_evaluation(
            Settings(repository_root=tmp_path), tmp_path, tmp_path / "output", dataset_file=dataset
        )
    assert not (tmp_path / "output").exists()
