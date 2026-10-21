"""Export fixed public Git revisions without executing their code or changing tests."""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class Pilot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    upstream: str = Field(pattern=r"^[a-z0-9-]+$")
    url: str
    before_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    fix: str = Field(pattern=r"^[a-f0-9]{40}$")
    issue: str
    repaired_file: str


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args], timeout=60)


def target_path(root: Path, path: str) -> Path:
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root.resolve()) or candidate == root.resolve():
        raise ValueError("Git object path escaped destination")
    return candidate


def extract(repo: Path, ref: str, destination: Path) -> dict[str, str]:
    destination.mkdir(parents=True)
    manifest = {}
    for entry in git(repo, "ls-tree", "-rz", "--full-tree", ref).split(b"\0"):
        if not entry:
            continue
        header, raw_path = entry.split(b"\t", 1)
        mode, kind, sha = header.decode().split()
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError("Pilot contains a link, submodule or unsupported Git object")
        path = raw_path.decode("utf8")
        data = git(repo, "cat-file", "blob", sha)
        target = target_path(destination, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest[path] = hashlib.sha256(data).hexdigest()
    return manifest


def prepare(upstream: Path, output: Path, spec_dir: Path) -> None:
    if output.exists():
        raise ValueError("Use a fresh output directory")
    pilots = [Pilot.model_validate(p) for p in json.loads((spec_dir / "spec.json").read_text())]
    output.mkdir(parents=True)
    (output / "acceptance").mkdir()
    records, dataset = [], []
    for pilot in pilots:
        repo = upstream / pilot.upstream
        source = output / "repos" / pilot.id
        hashes = extract(repo, pilot.before_commit, source)
        if pilot.upstream == "jsonpointer":
            (source / "tests").mkdir()
            (source / "tests/test_upstream_suite.py").write_text(
                '"""Collection adapter; the original upstream tests.py is unchanged."""\n'
                'import runpy\nimport unittest\nfrom pathlib import Path\n'
                '_suite = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tests.py"))\n'
                'for _name, _value in _suite.items():\n'
                '    if isinstance(_value, type) and issubclass(_value, unittest.TestCase):\n'
                '        globals()[_name] = _value\n', encoding="utf8")
        reference = output / "references" / pilot.id
        shutil.copytree(source, reference)
        target_path(reference, pilot.repaired_file).write_bytes(
            git(repo, "show", pilot.fix + ":" + pilot.repaired_file))
        acceptance = ("test_jsonpointer_large.py" if pilot.upstream == "jsonpointer"
                      else "test_itsdangerous_overflow.py")
        acceptance_bytes = (spec_dir / "acceptance" / (acceptance + ".txt")).read_bytes()
        (output / "acceptance" / acceptance).write_bytes(acceptance_bytes)
        records.append({**pilot.model_dump(), "upstream_files_sha256": hashes,
                        "acceptance_sha256": hashlib.sha256(acceptance_bytes).hexdigest()})
        dataset.append({"id": pilot.id, "issue": pilot.issue,
                        "repository": "repos/" + pilot.id, "acceptance": acceptance})
    (output / "provenance.json").write_text(json.dumps(records, indent=2), encoding="utf8")
    (output / "dataset.json").write_text(json.dumps(dataset, indent=2), encoding="utf8")
    print(f"Prepared {len(pilots)} fixed-revision pilots in {output.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True,
                        help="Directory with jsonpointer and itsdangerous read-only clones")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.upstream, args.output,
            Path(__file__).resolve().parents[1] / "docs/iteration2/pilots")


if __name__ == "__main__":
    main()
