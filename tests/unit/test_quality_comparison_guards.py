"""Comparison preflight rejects divergence before dispatch or task creation."""
import json

import pytest

from app.config.settings import Settings
from app.evaluation.historical import run
from app.evaluation.runner import run_evaluation


@pytest.mark.parametrize("problem", ["model", "overlap", "reversed", "not_fresh"])
def test_invalid_comparison_is_rejected_before_creating_tasks(tmp_path, problem):
    corpus = tmp_path / "corpus"
    (corpus / "sources/example").mkdir(parents=True)
    (corpus / "acceptance").mkdir()
    (corpus / "acceptance/test_contract.py").write_text("# metadata fixture only\n", encoding="utf-8")
    dataset = corpus / "dataset.json"
    dataset.write_text(json.dumps([{"id": "example", "repository": "sources/example",
        "acceptance": "test_contract.py", "issue": "Controlled metadata fixture only"}]), encoding="utf-8")
    common = Settings(_env_file=None, repository_root=corpus / "sources", data_dir=tmp_path / "unused",
        retry_workspace_policy="isolated", patch_transactions=True)
    variants = {"legacy": common.model_copy(update={"data_dir": tmp_path / "legacy"}),
                "quality": common.model_copy(update={"data_dir": tmp_path / "quality", "repair_quality_checks": True})}
    if problem == "model":
        variants["quality"].model_name = "different-model"
    elif problem == "overlap":
        variants["quality"].data_dir = variants["legacy"].data_dir / "nested"
    elif problem == "reversed":
        variants["legacy"].repair_quality_checks = True
    else:
        variants["quality"].data_dir.mkdir()
        (variants["quality"].data_dir / "previous.txt").write_text("preserve", encoding="utf-8")
    with pytest.raises(ValueError, match="Comparison"):
        run_evaluation(common, corpus / "sources", tmp_path / "output", repeats=4,
                       dataset_file=dataset, variants=variants)
    assert not (tmp_path / "output").exists()
    assert not (tmp_path / "legacy").exists()
    assert not (tmp_path / "unused").exists()


def test_variant_cannot_store_tasks_in_hidden_reference_tree(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    settings = Settings(_env_file=None, model_mode="live", repository_root=corpus / "sources",
        data_dir=tmp_path / "data", sandbox_image="sha256:" + "a" * 64,
        task_budgets=True, patch_transactions=True)
    variant = settings.model_copy(update={"data_dir": corpus / "references/tasks"})
    with pytest.raises(ValueError, match="whole corpus"):
        run(corpus, tmp_path / "output", "unused-lock", settings, repeats=4, variants={"quality": variant})
    assert not (corpus / "references").exists()
