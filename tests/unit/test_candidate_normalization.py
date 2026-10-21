"""Parsed text only: normalize representation without inventing code or evidence."""
import pytest

from app.agents.api_context import contract_api_context
from app.agents.normalization import normalize_candidate
from app.agents.quality import CandidateQualityError
from app.models.schemas import Edit, Patch
from app.tools.repository import Repository


def repo_fixture(tmp_path):
    (tmp_path / 'module.py').write_text("FIRST = 'one'\nSECOND = 'two'\n", encoding='utf-8')
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests/test_original.py').write_text('def test_original():\n    assert True\n', encoding='utf-8')
    return Repository(tmp_path)


def new_test():
    return Edit(path='tests/test_added.py', old='', new='def test_added():\n    assert VALUE == 3\n')


def test_independent_hunks_are_composed_at_original_offsets_not_sequential_replacement(tmp_path):
    repo = repo_fixture(tmp_path)
    original = repo.read_file('module.py')
    proposal = Patch(rationale='Explicit static normalization fixture', edits=[
        Edit(path='module.py', old="FIRST = 'one'", new='FIRST = "SECOND = \'two\'"'),
        Edit(path='module.py', old="SECOND = 'two'", new="SECOND = 'three'"), new_test()])
    candidate, facts = normalize_candidate(repo, proposal)
    assert len(candidate.edits) == 2
    staged = repo.stage(candidate)
    assert staged[repo.path('module.py')] == 'FIRST = "SECOND = \'two\'"\nSECOND = \'three\'\n'
    assert facts['normalization'][0]['input_edit_indices'] == [1, 2]
    assert facts['binding_origin'] == 'derived_from_actual_new_definitions'
    assert candidate.contract_tests == ['tests/test_added.py::test_added']
    assert proposal.contract_tests == [] and len(proposal.edits) == 3
    assert repo.read_file('module.py') == original and not (tmp_path / 'tests/test_added.py').exists()


@pytest.mark.parametrize('other_old', ["FIRST = 'one'", "'one'", "FIRST = 'modified'"])
def test_overlapping_or_dependent_edits_are_refused_without_writes(tmp_path, other_old):
    repo = repo_fixture(tmp_path)
    original = repo.read_file('module.py')
    proposal = Patch(rationale='Controlled invalid anchors', edits=[
        Edit(path='module.py', old="FIRST = 'one'", new="FIRST = 'modified'"),
        Edit(path='module.py', old=other_old, new="FIRST = 'another'"), new_test()])
    with pytest.raises(CandidateQualityError) as err:
        normalize_candidate(repo, proposal)
    assert err.value.diagnostics[0]['code'] in {'overlapping_edits', 'ambiguous_original_anchor'}
    assert repo.read_file('module.py') == original and not (tmp_path / 'tests/test_added.py').exists()


def test_multiple_new_file_creations_are_not_guessed_or_concatenated(tmp_path):
    repo = repo_fixture(tmp_path)
    proposal = Patch(rationale='Controlled ambiguous creation', edits=[new_test(), new_test()])
    with pytest.raises(CandidateQualityError, match='ambiguous_new_file'):
        normalize_candidate(repo, proposal)
    assert not (tmp_path / 'tests/test_added.py').exists()


@pytest.mark.parametrize('claim', ['tests/test_added.py::test_added with required behavior', 'tests/test_added.py', 'The code contains a regression for the stated contract'])
def test_real_test_definitions_are_bound_without_treating_prose_as_execution_evidence(tmp_path, claim):
    repo = repo_fixture(tmp_path)
    proposal = Patch(rationale='Controlled metadata normalization', edits=[new_test()], contract_tests=[claim])
    candidate, facts = normalize_candidate(repo, proposal)
    assert candidate.contract_tests == ['tests/test_added.py::test_added']
    assert facts['raw_proposal']['contract_tests'] == [claim]
    assert len(facts['raw_proposal_digest']) == 64
    assert not (tmp_path / 'tests/test_added.py').exists()


@pytest.mark.parametrize('claim', ['tests/test_missing.py::test_added', 'tests/test_added.py::test_missing', 'tests/test_original.py::test_original', '../outside.py::test_added'])
def test_false_explicit_claim_is_not_discarded_in_favor_of_real_tests(tmp_path, claim):
    repo = repo_fixture(tmp_path)
    proposal = Patch(rationale='Controlled false claim', edits=[new_test()],
                     contract_tests=['tests/test_added.py::test_added', claim])
    with pytest.raises(CandidateQualityError, match='unbound_test_claim'):
        normalize_candidate(repo, proposal)


def test_source_references_and_numeric_lines_do_not_become_fake_test_claims(tmp_path):
    repo = repo_fixture(tmp_path)
    proposal = Patch(rationale='Controlled mixed references', edits=[new_test()],
        contract_tests=['module.py: source contract; tests/test_added.py:1::test_added'])
    candidate, facts = normalize_candidate(repo, proposal)
    assert candidate.contract_tests == ['tests/test_added.py::test_added']
    assert facts['source_references_not_test_evidence'] == ['module.py']


def test_existing_tests_remain_immutable_even_with_composable_anchors(tmp_path):
    repo = repo_fixture(tmp_path)
    before = repo.read_file('tests/test_original.py')
    proposal = Patch(rationale='Controlled forbidden test edit', edits=[
        Edit(path='tests/test_original.py', old='assert True', new='assert False'),
        Edit(path='tests/test_original.py', old='test_original', new='test_modified'), new_test()])
    with pytest.raises(ValueError, match='immutable'):
        normalize_candidate(repo, proposal)
    assert repo.read_file('tests/test_original.py') == before


def test_combined_span_cannot_bypass_existing_schema_size_limit(tmp_path):
    repo = repo_fixture(tmp_path)
    (tmp_path / 'module.py').write_text('A = 1\n#' + 'x' * 60000 + '\nB = 2\n', encoding='utf-8')
    proposal = Patch(rationale='Controlled oversized span', edits=[
        Edit(path='module.py', old='A = 1', new='A = 3'),
        Edit(path='module.py', old='B = 2', new='B = 4'), new_test()])
    with pytest.raises(CandidateQualityError, match='composed_edit_too_large'):
        normalize_candidate(repo, proposal)


def test_api_beyond_module_prefix_is_shown_with_real_defaults_without_import(tmp_path):
    repo = repo_fixture(tmp_path)
    marker = tmp_path / 'MUST_NOT_EXIST'
    source = f'from pathlib import Path\nPath({str(marker)!r}).touch()\n' + '# padding\n' * 2000
    source += 'def requested(text, separator=" "):\n    return separator.join(text.split())\n'
    (tmp_path / 'module.py').write_text(source, encoding='utf-8')
    context, facts = contract_api_context(repo, ['module.py'], 'Preserve requested separator behavior', 2000)
    assert 'def requested(text, separator=" ")' in context
    assert len(context) <= 2000 and facts['context_chars'] == len(context)
    assert facts['api_slices'][0]['start_line'] > 2000
    assert facts['snapshot'] == 'isolated_candidate_original_before_patch'
    assert not marker.exists()


def test_class_qualified_api_identity_is_preserved(tmp_path):
    repo = repo_fixture(tmp_path)
    (tmp_path / 'module.py').write_text('class First:\n    def calculate(self):\n        return 1\nclass Second:\n    def calculate(self):\n        return 2\n', encoding='utf-8')
    _, facts = contract_api_context(repo, ['module.py'], 'Inspect calculate in First and Second', 3000)
    assert {f['symbol'] for f in facts['api_slices']} == {'First.calculate', 'Second.calculate'}
