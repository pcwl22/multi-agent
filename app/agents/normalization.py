"""Lossless original-anchored edit composition and source-derived test bindings."""
import json
import re
from collections import defaultdict
from pathlib import Path

from app.agents.quality import (
    CandidateQualityError,
    QualityDiagnostic,
    test_functions,
    validate_candidate,
)
from app.models.schemas import Edit, Patch
from app.tools.repository import Repository, digest, is_test_file


def reject(code: str, path: str, indices: list[int], correction: str) -> None:
    raise CandidateQualityError([QualityDiagnostic(code=code, path=path, edit_indices=indices, correction=correction)])


def normalize_candidate(repo: Repository, proposal: Patch) -> tuple[Patch, dict]:
    groups: dict[Path, list[tuple[int, Edit]]] = defaultdict(list)
    for index, edit in enumerate(proposal.edits, 1):
        groups[repo.path(edit.path, existing=False)].append((index, edit))
    edits, composed = [], []
    for path, group in groups.items():
        relative = path.relative_to(repo.root).as_posix()
        indices = [i for i, _ in group]
        if len(group) == 1:
            e = group[0][1]
            edits.append(Edit(path=relative, old=e.old, new=e.new))
            continue
        if not path.exists():
            reject('ambiguous_new_file', relative, indices, 'Return one complete NEW file; multiple creations cannot be concatenated safely.')
        if path.suffix != '.py' or path.name.casefold() == 'conftest.py' or is_test_file(relative):
            raise ValueError('Existing tests, pytest configuration and non-Python files are immutable')
        source = repo.read_file(relative, 100000)
        spans = []
        for index, e in group:
            if not e.old or source.count(e.old) != 1:
                reject('ambiguous_original_anchor', relative, [index], 'Every hunk must match exactly once in the ORIGINAL file; dependent or intermediate-state anchors are refused.')
            start = source.index(e.old)
            spans.append((start, start + len(e.old), e.new, index))
        spans.sort(key=lambda item: item[0])
        if any(current[0] < previous[1] for previous, current in zip(spans, spans[1:])):
            reject('overlapping_edits', relative, indices, 'Overlapping original ranges cannot be merged. Return one complete unambiguous replacement; nothing was written.')
        low, high = spans[0][0], spans[-1][1]
        replacement = source[low:high]
        for start, end, new, _ in reversed(spans):
            replacement = replacement[:start-low] + new + replacement[end-low:]
        if len(source[low:high]) > 50000 or len(replacement) > 50000:
            reject('composed_edit_too_large', relative, indices, 'The combined Edit exceeds the existing schema limit. Return a smaller complete unique replacement.')
        edits.append(Edit(path=relative, old=source[low:high], new=replacement))
        composed.append({'path': relative, 'input_edit_indices': indices,
                         'original_ranges': [[s, e] for s, e, _, _ in spans], 'method': 'simultaneous_nonoverlapping_original_anchors'})
    candidate = Patch(rationale=proposal.rationale, edits=edits)
    staged = repo.stage(candidate)
    inventory = {path.relative_to(repo.root).as_posix(): test_functions(text) for path, text in staged.items()
                 if not path.exists() and is_test_file(path.relative_to(repo.root))}
    actual = [path + '::' + name for path, tests in inventory.items() for name in tests]
    if not actual:
        reject('missing_new_tests', '', [], 'Include actual NEW test definitions in this complete candidate; original tests stay immutable.')
    resolved, unstructured, source_references = [], [], []
    for claim in proposal.contract_tests:
        tokens = [t.strip('[]*.,:') for t in re.split(r"[\s'\"`(),;]+", claim) if '.py' in t]
        if not tokens:
            unstructured.append(claim)  # Preserved as model prose, never treated as test evidence.
        for token in tokens:
            token = re.sub(r'(\.py):([0-9]+)(?=::|$)', r'\1', token)
            if '::' not in token:
                token = re.sub(r'(\.py):([A-Za-z_]\w*(?:::[A-Za-z_]\w*)?)$', r'\1::\2', token)
            pieces = token.split('::')
            try:
                path = repo.path(pieces[0], existing=False).relative_to(repo.root).as_posix()
            except ValueError:
                reject('unbound_test_claim', token[:500], [], 'Explicit test paths must resolve to actual NEW files in this candidate.')
            if path not in inventory and not is_test_file(path) and repo.path(path, existing=False).is_file():
                source_references.append(token)  # A source reference is not a NEW-test claim.
                continue
            if path not in inventory:
                reject('unbound_test_claim', token[:500], [], 'This explicit path is absent or belongs to an original test. Reference an actual NEW test file.')
            if len(pieces) > 1:
                definition = '::'.join(part.split('[', 1)[0] for part in pieces[1:])
                if definition not in inventory[path]:
                    reject('unbound_test_claim', token[:500], [], 'This named test definition does not exist in the NEW file.')
                resolved.append(path + '::' + definition)
            else:
                resolved.extend(path + '::' + name for name in inventory[path])
    bindings = list(dict.fromkeys(resolved or actual))
    candidate.contract_tests = bindings[:32]
    facts = validate_candidate(repo, candidate)
    facts.update(version=2, normalization=composed, binding_origin='resolved_explicit_claims' if resolved else 'derived_from_actual_new_definitions',
        binding_count_before_limit=len(bindings), binding_limit=32,
        unstructured_claims_not_evidence=unstructured, source_references_not_test_evidence=source_references, raw_proposal=proposal.model_dump(),
        raw_proposal_digest=digest(json.dumps(proposal.model_dump(), sort_keys=True, separators=(',', ':'), ensure_ascii=False)))
    return candidate, facts
