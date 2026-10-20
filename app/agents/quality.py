"""Candidate contract checks using bounded AST data; never execute target code."""
import ast
import re
from collections import defaultdict

from pydantic import Field

from app.models.schemas import Patch, StrictModel
from app.tools.repository import Repository, digest, is_test_file


class QualityDiagnostic(StrictModel):
    code: str
    path: str = ""
    edit_indices: list[int] = Field(default_factory=list)
    correction: str


class CandidateQualityError(ValueError):
    def __init__(self, diagnostics: list[QualityDiagnostic]):
        self.diagnostics = [d.model_dump() for d in diagnostics]
        super().__init__("Candidate quality rejected: " + "; ".join(d.code + (": " + d.path if d.path else "") for d in diagnostics))


def test_functions(source: str) -> dict[str, list[str]]:
    """List statically declared test identities and assertions, not runtime coverage."""
    tree = ast.parse(source)
    result = {}
    def add(node: ast.AST, prefix: str = "") -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            result[prefix + node.name] = [ast.unparse(n)[:1000] for n in ast.walk(node) if isinstance(n, ast.Assert)][:12]
    for node in tree.body:
        add(node)
        if isinstance(node, ast.ClassDef) and (node.name.startswith("Test") or any(
            ast.unparse(base).endswith("TestCase") for base in node.bases
        )):
            for child in node.body:
                add(child, node.name + "::")
    return result


def protocol(version: int = 1) -> dict:
    value = {
        "version": 1,
        "edits": "Exactly ONE Edit per canonical file path. Combine all changes for that file into one unique old substring and its replacement. Do not submit multiple hunks as separate Edit entries. Never edit original tests.",
        "contract_tests": "Nonempty exact identities: tests/test_new.py::test_name or tests/test_new.py::TestClass::test_name. Each must name a NEW file and an actual test definition in this complete candidate. No prose or invented paths.",
        "candidate": "Fresh original workspace: include ALL source changes and NEW test files, even after a rejected previous candidate. Archived files do not exist here.",
        "example": {"edits": [{"path": "module.py", "old": "unique old block", "new": "complete replacement block"}, {"path": "tests/test_new.py", "old": "", "new": "def test_name():\n    assert observed_behavior() == required_value\n"}], "contract_tests": ["tests/test_new.py::test_name"]},
        "regression": "The SAME added tests will run on original source in Docker. At least one collected test must fail there and pass with this candidate. Collection errors and tests passing both versions are not a regression witness.",
    }

    if version == 2:
        value.update(version=2,
            edits="Prefer ONE Edit per file. Independent non-overlapping hunks can be losslessly composed only when EACH old snippet matches exactly once in the ORIGINAL source. Overlap, dependent anchors and multiple creations are rejected; no guessing or sequential application.",
            contract_tests="You may give exact NEW file::test identities. Actual test bindings are derived from the NEW source definitions if metadata is omitted; this is not semantic proof. If you name a test file or definition it must exist in this complete candidate. Pure prose is preserved as an unverified claim, not test evidence.")
    return value


def validate_candidate(repo: Repository, patch: Patch) -> dict:
    paths: dict[object, list[int]] = defaultdict(list)
    for index, edit in enumerate(patch.edits, 1):
        paths[repo.path(edit.path, existing=False)].append(index)
    duplicates = [QualityDiagnostic(code="duplicate_file_edits", path=p.relative_to(repo.root).as_posix(), edit_indices=indices,
        correction="One edit per file is required. Return one complete Edit for this path, with a unique original old block spanning the changes. Do not concatenate overlapping edits or rely on the previous candidate.")
        for p, indices in paths.items() if len(indices) > 1]
    if duplicates:
        raise CandidateQualityError(duplicates)
    staged = repo.stage(patch)  # Validate every path, precondition and syntax before any write.
    added = {p.relative_to(repo.root).as_posix(): text for p, text in staged.items()
             if is_test_file(p.relative_to(repo.root)) and not p.exists()}
    inventory = {p: test_functions(text) for p, text in added.items()}
    problems = []
    if not any(inventory.values()):
        problems.append(QualityDiagnostic(code="missing_new_tests", correction="Include a NEW test file with collected test definitions in this complete candidate; original tests cannot be changed."))
    if not patch.contract_tests:
        problems.append(QualityDiagnostic(code="missing_test_bindings", correction="Populate contract_tests with exact NEW file::test_definition identities, not just a claim in rationale."))
    for binding in patch.contract_tests:
        match = re.fullmatch(r"([^:\s]+\.py)::([A-Za-z_]\w*(?:::[A-Za-z_]\w*)?)", binding)
        path, name = match.groups() if match else ("", "")
        if path not in inventory or name not in inventory.get(path, {}):
            problems.append(QualityDiagnostic(code="unbound_test_claim", path=binding[:500],
                correction="Reference an actual test definition in a NEW file included in this candidate, using path.py::test_name (or ::Class::test_name)."))
    if problems:
        raise CandidateQualityError(problems)
    return {"version": 1, "new_test_definitions": {p: list(tests) for p, tests in inventory.items()},
            "contract_tests": patch.contract_tests,
            "staged_content_digests": {p.relative_to(repo.root).as_posix(): digest(text) for p, text in staged.items()}}


def failed_assertions(repo: Repository, feedback: list[dict]) -> list[dict]:
    output = []
    consumed = 0
    for item in feedback[-2:]:
        for observation in item.get("observations", []):
            if observation.get("origin") != "original_test":
                continue
            name = observation.get("test", "").split("[", 1)[0]
            try:
                path = observation["file"]
                source = repo.read_file(path, 100000)
                tests = test_functions(source)
                assertions = [a for key, values in tests.items() if key.split("::")[-1] == name for a in values]
            except (ValueError, OSError, SyntaxError, UnicodeError):
                continue
            assertions = [a[:500] for a in assertions[:4]]
            consumed += sum(len(a) for a in assertions)
            if consumed > 6000:
                return output[:8]
            output.append({"file": path, "test": name, "source_text_sha256": digest(source),
                           "original_assertions": assertions, "observed_message": observation.get("message", "")[:1000]})
    return output[:8]
