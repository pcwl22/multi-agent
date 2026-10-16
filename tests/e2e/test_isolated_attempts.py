"""Three controlled wrong-test scenarios, with actual Docker and no live model."""

import hashlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config.settings import Settings
from app.models.schemas import Edit, Patch, TaskRequest
from app.services.tasks import TaskService

pytestmark = [pytest.mark.docker, pytest.mark.skipif(
    os.environ.get("REPOPILOT_RUN_DOCKER_TESTS") != "1", reason="Docker tests are opt-in"
)]

CASES = {
    "page-tail": (
        "def calculate(items, page, size):\n    return items[page * size:page * size + size]\n",
        "def calculate(items, page, size):\n    return list(items[(page-1)*size:page*size])\n",
        "assert calculate(range(1,8), 4, 2) == []",
        "assert calculate(range(1,8), 4, 2) == [7]",
        "assert calculate([], 1, 2) == []",
    ),
    "numeric-type": (
        "def calculate(amount, percent):\n    return round(amount * (1-percent), 2)\n",
        "def calculate(amount, percent):\n    return round(amount * (1-percent/100), 2)\n",
        "assert isinstance(calculate(100, 20), int)",
        "assert calculate(100, 20) == 80",
        "assert calculate(0, 0) == 0",
    ),
    "unsigned-encoding": (
        "import struct\n\ndef encode(n):\n    return struct.pack('>Q', n)\n\n"
        "class BadTimestamp(Exception):\n    pass\n\ndef calculate(n):\n"
        "    if n > 9999:\n        raise ValueError('year overflow')\n    return n\n",
        "import struct\n\ndef encode(n):\n    return struct.pack('>Q', n)\n\n"
        "class BadTimestamp(Exception):\n    pass\n\ndef calculate(n):\n"
        "    if n > 9999:\n        raise BadTimestamp('malformed timestamp')\n    return n\n",
        "calculate(encode(-(10**18)))",
        "with pytest.raises(BadTimestamp):\n        calculate(10**12)",
        "assert calculate(1) == 1",
    ),
}


class CandidateFixture:
    def __init__(self, case, *, always_bad=False):
        self.original, self.fixed, self.bad, self.good, _ = CASES[case]
        self.calls = 0
        self.always_bad = always_bad

    def generate(self, schema, payload):
        assert schema is Patch and payload["retry_workspace_policy"] == "isolated"
        assert self.original in payload["context"]
        assert "tests/test_generated.py" not in payload["existing_test_paths"]
        if self.calls:
            assert payload["tests"][-1]["status"] == "failed"
            assert payload["previous_candidate_diff"]
        self.calls += 1
        assertion = self.bad if self.calls == 1 or self.always_bad else self.good
        code = "import pytest\nfrom target import *\n\ndef test_generated():\n    " + assertion + "\n"
        return Patch(rationale="Controlled fixture, not a model-generated repair", edits=[
            Edit(path="target.py", old=self.original, new=self.fixed),
            Edit(path="tests/test_generated.py", old="", new=code),
        ]), {"calls": 0, "input_tokens": 0, "output_tokens": 0, "adapter": "test-fixture"}


def make_service(tmp_path, case, *, always_bad=False):
    source = tmp_path / "source"
    (source / "tests").mkdir(parents=True)
    (source / "target.py").write_text(CASES[case][0], encoding="utf8")
    (source / "tests/test_original.py").write_text(
        "from target import calculate\n\ndef test_original():\n    " + CASES[case][4] + "\n",
        encoding="utf8")
    model = CandidateFixture(case, always_bad=always_bad)
    settings = Settings(repository_root=source, data_dir=tmp_path / "data", max_retries=1,
                        retry_workspace_policy="isolated")
    service = TaskService(settings, model=model)
    task = service.create(TaskRequest(repository_path=str(source), mode="single",
                                      issue_description="Repair the stated public function contract"))
    return service, task, source, model


@pytest.mark.parametrize("case", CASES)
def test_wrong_generated_test_is_preserved_while_fresh_candidate_can_pass(tmp_path, case):
    service, task, source, model = make_service(tmp_path, case)
    original_test = (source / "tests/test_original.py").read_bytes()
    try:
        result = service.run(task["task_id"])
        assert result["execution_status"] == "awaiting_approval"
        assert result["attempts"] == model.calls == 2 and result["retry_count"] == 1
        assert result["candidate_number"] == 2 and len(result["attempt_history"]) == 1
        assert [t["status"] for t in result["test_results"]] == ["failed", "passed"]
        assert all(t["evidence"] == "docker" and t["image_id"] for t in result["test_results"])
        previous = result["attempt_history"][0]
        old_test = Path(previous["workspace_path"]) / "tests/test_generated.py"
        old_bytes = old_test.read_bytes()
        assert CASES[case][2] in old_bytes.decode()
        assert previous["candidate_id"] != result["candidate_id"]
        for workspace in [Path(previous["workspace_path"]), Path(result["workspace_path"])]:
            assert (workspace / "tests/test_original.py").read_bytes() == original_test
        assert (source / "tests/test_original.py").read_bytes() == original_test
        assert (source / "target.py").read_text(encoding="utf8") == CASES[case][0]
        with TestClient(create_app(service=service)) as api:
            for candidate in [None, previous["candidate_id"]]:
                response = api.post(f"/api/tasks/{task['task_id']}/approve", json={
                    "diff_digest": result["diff_digest"], "candidate_id": candidate,
                })
                assert response.status_code == 409
                assert "candidate" in response.json()["detail"]
            approved = api.post(f"/api/tasks/{task['task_id']}/approve", json={
                "diff_digest": result["diff_digest"], "candidate_id": result["candidate_id"],
            })
            assert approved.status_code == 200
            assert approved.json()["approved_candidate_id"] == result["candidate_id"]
        with pytest.raises(ValueError, match="approved candidate"):
            service.publish(task["task_id"], result["diff_digest"], candidate_id=previous["candidate_id"])
        assert old_test.read_bytes() == old_bytes
        assert hashlib.sha256(old_bytes).hexdigest() == previous["workspace_manifest"]["tests/test_generated.py"]
    finally:
        service.close()


def test_wrong_candidates_exhaust_same_retry_budget_without_removing_any_test(tmp_path):
    service, task, _, model = make_service(tmp_path, "page-tail", always_bad=True)
    try:
        result = service.run(task["task_id"])
        assert result["execution_status"] == "failed"
        assert result["error"] == "Test retry budget exhausted"
        assert result["attempts"] == model.calls == 2 and result["retry_count"] == 1
        assert len(result["attempt_history"]) == 1
        for number in [1, 2]:
            assert (Path(result["task_path"]) / "attempts" / f"{number:04}" /
                    "workspace/tests/test_generated.py").is_file()
    finally:
        service.close()
