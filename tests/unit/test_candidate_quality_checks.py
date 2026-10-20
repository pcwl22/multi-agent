"""Controlled text fixtures only; no target Python executes on the host."""
import json

import pytest

from app.agents.quality import CandidateQualityError, failed_assertions, validate_candidate
from app.agents.review_evidence import review_packet
from app.models.schemas import Edit, Patch
from app.tools.repository import Repository


def repository(tmp_path):
    (tmp_path / "code.py").write_text("VALUE = 0\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_original.py").write_text("def test_original():\n    assert 'Malformed' in message\n", encoding="utf-8")
    return Repository(tmp_path)


def candidate():
    return Patch(rationale="Controlled static fixture", edits=[
        Edit(path="code.py", old="VALUE = 0", new="VALUE = 1"),
        Edit(path="tests/test_new.py", old="", new="def test_fixed():\n    assert VALUE == 1\n")],
        contract_tests=["tests/test_new.py::test_fixed"])


def test_duplicate_diagnostics_identify_all_indices_without_writes(tmp_path):
    repo = repository(tmp_path)
    patch = candidate()
    patch.edits += [Edit(path="code.py", old="VALUE = 0", new="VALUE = 2")]
    with pytest.raises(CandidateQualityError) as err:
        validate_candidate(repo, patch)
    assert err.value.diagnostics[0]["edit_indices"] == [1, 3]
    assert err.value.diagnostics[0]["path"] == "code.py"
    assert "One edit per file" in err.value.diagnostics[0]["correction"]
    assert repo.read_file("code.py") == "VALUE = 0\n"
    assert not (tmp_path / "tests/test_new.py").exists()


@pytest.mark.parametrize("claim", ["tests/test_missing.py::test_fixed", "tests/test_new.py::test_missing", "tests/test_original.py::test_original", "../test_new.py::test_fixed", "the tests cover everything"])
def test_unbound_claims_rejected_before_any_write(tmp_path, claim):
    repo = repository(tmp_path)
    patch = candidate()
    patch.contract_tests = [claim]
    with pytest.raises(CandidateQualityError) as err:
        validate_candidate(repo, patch)
    assert any(d["code"] == "unbound_test_claim" for d in err.value.diagnostics)
    assert repo.read_file("code.py") == "VALUE = 0\n"
    assert not (tmp_path / "tests/test_new.py").exists()


def test_complete_candidate_inventory_binds_test_definitions(tmp_path):
    repo = repository(tmp_path)
    evidence = validate_candidate(repo, candidate())
    assert evidence["new_test_definitions"] == {"tests/test_new.py": ["test_fixed"]}
    assert set(evidence["staged_content_digests"]) == {"code.py", "tests/test_new.py"}
    assert not (tmp_path / "tests/test_new.py").exists()


def test_missing_tests_and_bindings_are_both_reported(tmp_path):
    repo = repository(tmp_path)
    patch = Patch(rationale="Controlled incomplete retry", edits=candidate().edits[:1])
    with pytest.raises(CandidateQualityError) as err:
        validate_candidate(repo, patch)
    assert {x["code"] for x in err.value.diagnostics} == {"missing_new_tests", "missing_test_bindings"}


def test_original_assertion_text_survives_runtime_value_rendering(tmp_path):
    repo = repository(tmp_path)
    feedback = [{"observations": [{"file": "tests/test_original.py", "test": "test_original", "origin": "original_test", "message": "assert 'Malformed' in 'Signature mismatch'"}]}]
    facts = failed_assertions(repo, feedback)
    assert facts[0]["original_assertions"] == ["assert 'Malformed' in message"]


def test_review_packet_shows_passing_test_assertions_and_marks_omission(tmp_path):
    repo = repository(tmp_path)
    current = {"status": "passed", "diff_digest": "fixed", "candidate_id": "candidate",
               "evidence": "explicit-unit-double", "image_id": None, "stdout": "x" * 20000,
               "cases": [{"file": "tests/test_original.py", "name": "test_original", "status": "passed"}]}
    state = {"test_results": [current], "candidate_id": "candidate", "diff_digest": "fixed",
             "issue_description": "Malformed timestamp", "patches": [{"changed_files": ["code.py"]}],
             "located_files": ["tests/test_original.py"]}
    packet = review_packet(repo, state, 24000)
    fact = packet["review_evidence"]["test_facts"][0]
    assert fact["static_assertions"] == {"test_original": ["assert 'Malformed' in message"]}
    assert fact["status"] == "passed" and fact["evidence"] == "explicit-unit-double"
    assert len(packet["test_result"]["stdout"]) == 2000
    assert "unknown" in packet["review_evidence"]["interpretation"]
    assert len(json.dumps(packet["review_evidence"]["test_facts"])) < 8000
    state["candidate_id"] = "another"
    with pytest.raises(ValueError, match="current candidate"):
        review_packet(repo, state, 24000)


def test_forged_test_and_configuration_edits_remain_immutable(tmp_path):
    repo = repository(tmp_path)
    patch = candidate()
    patch.edits[1] = Edit(path="tests/test_original.py", old="message", new="'Malformed'")
    before = (tmp_path / "tests/test_original.py").read_bytes()
    with pytest.raises(ValueError, match="immutable"):
        validate_candidate(repo, patch)
    assert (tmp_path / "tests/test_original.py").read_bytes() == before


def test_alias_paths_do_not_bypass_duplicate_check(tmp_path):
    repo = repository(tmp_path)
    patch = candidate()
    patch.edits.append(Edit(path="./code.py", old="VALUE = 0", new="VALUE = 2"))
    # Both strict path rejection and canonical duplicate rejection are safe; no partial write.
    with pytest.raises(ValueError):
        validate_candidate(repo, patch)
    assert repo.read_file("code.py") == "VALUE = 0\n"


def test_no_fixture_execution_is_needed_for_inventory(tmp_path):
    repo = repository(tmp_path)
    patch = candidate()
    marker = tmp_path / "MUST_NOT_EXIST"
    patch.edits[1].new = f"from pathlib import Path\nPath({str(marker)!r}).touch()\ndef test_fixed():\n    assert VALUE == 1\n"
    validate_candidate(repo, patch)
    assert not marker.exists()


def test_explicit_demo_adapter_binds_new_tests_only_under_quality_protocol():
    from app.agents.demo_fixtures import select_fixture
    from app.agents.model import MockModel
    fixture = select_fixture("expired")
    payload = {"issue_description": "expired", "context": fixture.old}
    legacy, _ = MockModel().generate(Patch, payload)
    quality, stats = MockModel().generate(Patch, {**payload, "candidate_protocol": {"version": 1}})
    assert legacy.contract_tests == []
    assert quality.contract_tests and all(x.startswith(fixture.regression_path + "::") for x in quality.contract_tests)
    assert stats["adapter"] == "mock" and stats["calls"] == 0


def test_review_assertions_do_not_mix_same_named_methods_in_different_classes(tmp_path):
    repo = repository(tmp_path)
    (tmp_path / "tests/test_original.py").write_text("class TestFirst:\n    def test_same(self):\n        assert VALUE == 1\nclass TestSecond:\n    def test_same(self):\n        assert VALUE == 2\n", encoding="utf-8")
    current = {"status": "passed", "diff_digest": "fixed", "evidence": "explicit-unit-double", "cases": [
        {"file": "tests/test_original.py", "name": "test_same", "classname": "tests.test_original.TestSecond", "status": "passed"}]}
    state = {"test_results": [current], "diff_digest": "fixed", "issue_description": "Controlled fixture",
        "patches": [{"changed_files": []}], "located_files": []}
    packet = review_packet(repo, state, 24000)
    assert packet["review_evidence"]["test_facts"][0]["static_assertions"] == {"TestSecond::test_same": ["assert VALUE == 2"]}
