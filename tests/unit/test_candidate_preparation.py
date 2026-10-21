from pathlib import Path

import pytest

from app.services.attempts import file_manifest, prepare_candidate


def baseline(tmp_path):
    source = tmp_path / "baseline"
    source.mkdir()
    (source / "target.py").write_text("value = 1\n", encoding="utf8")
    return file_manifest(source)


def test_prepared_but_uncheckpointed_candidate_is_reused_with_same_identity(tmp_path):
    manifest = baseline(tmp_path)
    first = prepare_candidate(tmp_path, 1, manifest)
    assert prepare_candidate(tmp_path, 1, manifest) == first
    assert file_manifest(Path(first["workspace_path"])) == manifest


def test_partial_staging_directory_survives_and_does_not_contaminate_retry(tmp_path):
    manifest = baseline(tmp_path)
    orphan = tmp_path / "attempts/preparing-interrupted/partial.txt"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("preserved diagnostic evidence", encoding="utf8")
    prepare_candidate(tmp_path, 1, manifest)
    assert orphan.read_text() == "preserved diagnostic evidence"
    assert file_manifest(tmp_path / "baseline") == manifest


def test_unrecorded_candidate_writes_are_refused_without_resetting_files(tmp_path):
    manifest = baseline(tmp_path)
    candidate = prepare_candidate(tmp_path, 1, manifest)
    target = Path(candidate["workspace_path"]) / "target.py"
    target.write_text("value = 2\n", encoding="utf8")
    with pytest.raises(ValueError, match="Unrecorded candidate writes"):
        prepare_candidate(tmp_path, 1, manifest)
    assert target.read_text() == "value = 2\n"


def test_original_baseline_cannot_change_between_attempts(tmp_path):
    manifest = baseline(tmp_path)
    prepare_candidate(tmp_path, 1, manifest)
    (tmp_path / "baseline/target.py").write_text("value = 999\n", encoding="utf8")
    with pytest.raises(ValueError, match="Original baseline changed"):
        prepare_candidate(tmp_path, 2, manifest)
