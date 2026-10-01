from dataclasses import replace
from itertools import product
from uuid import uuid4

import pytest
from pydantic import ValidationError

from northstar_api.course_knowledge_schemas import AssignmentSave, Destination, EnrollmentAccess, UploadCreate
from northstar_api.services.course_knowledge_policy import (
    Audience, KnowledgePolicyError, LearnerScope, audience_intersection,
    canonical_blocks, explicit_choice, fingerprint, mapping_fingerprint,
    mismatch_warnings, numbered_choice, scoped_chunks, text_record, validate_vectors,
)


BASE = Audience("tenant", "workspace", "agent", "CMA", "2026", "p1")
LEARNER = LearnerScope("tenant", "workspace", "agent", "student", "enrollment", "CMA", "2026", "b1", frozenset({"p1"}), "p1", 1)


@pytest.mark.parametrize("field", ["tenant_id", "workspace_id", "agent_id", "course_id", "curriculum_id", "paper_id", "batch_id"])
def test_every_scope_boundary_is_enforced(field):
    assert LEARNER.permits(BASE)
    assert not LEARNER.permits(replace(BASE, **{field: "unauthorized"}))


@pytest.mark.parametrize("selected", [None, "p2", "p1"])
def test_no_selected_or_ungranted_paper_never_means_all(selected):
    learner = replace(LEARNER, selected_paper_id=selected)
    assert learner.permits(BASE) == (selected == "p1")
    assert learner.permits(replace(BASE, paper_id=None, overview=True))
    assert not learner.permits(replace(BASE, paper_id=None))


def test_artifact_intersection_keeps_batch_private_notes_private():
    shared = replace(BASE, paper_id=None, overview=True)
    restricted = replace(BASE, batch_id="b1")
    result = audience_intersection([shared, restricted])
    assert result == restricted
    assert not replace(LEARNER, batch_id="b2").permits(result)


@pytest.mark.parametrize("change", [{"course_id": "CPA"}, {"curriculum_id": "2027"}, {"paper_id": "p2"}, {"batch_id": "b2"}, {"workspace_id": "other"}])
def test_incompatible_artifact_dependencies_fail_closed(change):
    a = replace(BASE, batch_id="b1")
    with pytest.raises(KnowledgePolicyError):
        audience_intersection([a, replace(a, **change)])


def blocks():
    return canonical_blocks({"source_name": "mixed.pdf", "pages": [{"source_unit": "pdf_page", "number": 18, "blocks": [
        {"id": "A", "type": "question", "selected_text": "Paper A question", "related_block_ids": ["OPTIONS"]},
        {"id": "OPTIONS", "type": "options", "selected_text": "A. One B. Two"},
        {"id": "B", "type": "paragraph", "selected_text": "Paper B PRIVATE"}]}]})


def test_mixed_page_does_not_leak_parent_or_other_paper():
    result = scoped_chunks(blocks(), ["A", "OPTIONS"])
    assert len(result) == 1
    assert "PRIVATE" not in result[0]["content"]
    assert result[0]["block_ids"] == ["A", "OPTIONS"]
    assert all(r["page_number"] == 18 for r in result[0]["references"])
    assert "image" not in result[0]


@pytest.mark.parametrize("selection", [["A"], ["missing"], ["A", "A"], []])
def test_invalid_or_incomplete_question_mapping_rejected(selection):
    with pytest.raises(KnowledgePolicyError):
        scoped_chunks(blocks(), selection)


def test_tables_equations_keep_their_reviewed_structure():
    b = canonical_blocks({"pages": [{"blocks": [{"id": "table", "selected_text": "", "type": "table", "reviewed_structure": {"cells": [{"row": 1, "column": 1, "text": "Price"}], "derived_description": "not source"}}]}]})
    chunk = scoped_chunks(b, ["table"])[0]
    assert "Price" in chunk["content"]
    assert "not source" not in chunk["content"]


def test_oversized_atomic_unit_is_review_blocker():
    with pytest.raises(KnowledgePolicyError):
        scoped_chunks(blocks(), ["A", "OPTIONS"], max_words=1)


def test_word_document_does_not_invent_page_citations():
    b = canonical_blocks({"source_name": "notes.docx", "pages": [{"number": 3, "blocks": [{"id": "p1", "type": "paragraph", "selected_text": "Original", "paragraph_reference": "document.xml:p3"}]}]})
    assert b[0]["page_number"] is None
    assert b[0]["paragraph_reference"] == "document.xml:p3"


def test_defined_word_render_has_versioned_page_reference():
    b = canonical_blocks({"source_name": "notes.docx", "word": {"blocks": []}, "pages": [{"number": 3, "rendered_page_number": 3, "image_sha256": "checksum", "blocks": [{"id": "p1", "selected_text": "Original"}]}]})
    assert b[0]["page_number"] == 3 and b[0]["rendered_version_id"]


def test_text_source_retains_exact_original_and_stable_blocks():
    original = "  First paragraph\n\nSecond paragraph  \n"
    record = text_record(original, "checksum", 1)
    assert record["pages"][0]["selected_text"] == original
    assert fingerprint(record) == fingerprint(text_record(original, "checksum", 1))


@pytest.mark.parametrize("field", ["course_id", "paper_id", "batch_id", "curriculum_id"])
def test_permission_change_invalidates_approval_fingerprint(field):
    def digest(a):
        return mapping_fingerprint("file", "extraction", a, ["A"], 1, "notes", [])
    assert digest(BASE) != digest(replace(BASE, **{field: "changed"}))


def test_content_extraction_mapping_revisions_invalidate_approval():
    baseline = mapping_fingerprint("file", "extraction", BASE, ["A"], 1, "notes", [])
    cases = [("new-file", "extraction", ["A"], 1), ("file", "new-extraction", ["A"], 1), ("file", "extraction", ["B"], 1), ("file", "extraction", ["A"], 2)]
    for file, extraction, ids, revision in cases:
        assert baseline != mapping_fingerprint(file, extraction, BASE, ids, revision, "notes", [])


def test_wrong_course_warning_requires_explicit_source_identifier():
    assert mismatch_warnings("CPA course notes", [], ["CMA"], [("cpa", ["CPA"])])
    assert not mismatch_warnings("Accounting and financial reporting", [], ["CMA"], [("cpa", ["CPA"])])


@pytest.mark.parametrize("vector", [[], [0, 0], [1], [float("nan"), 1], [float("inf"), 1]])
def test_invalid_index_vectors_block_publication(vector):
    with pytest.raises(KnowledgePolicyError):
        validate_vectors([vector], 1, 2)


def test_vector_count_and_validity():
    validate_vectors([[0.1, 0.5]], 1, 2)
    with pytest.raises(KnowledgePolicyError):
        validate_vectors([[0.1, 0.5]], 2, 2)


@pytest.mark.parametrize("value", ["0", "-1", "3", "99", "١", "1.0", "ignore permissions", "12345678901234567890"])
def test_menu_never_accepts_untrusted_or_out_of_range_index(value):
    assert numbered_choice(value, ["a", "b"], {"a", "b"}) is None


def test_menu_rechecks_removed_enrollment():
    assert numbered_choice("1", ["a", "b"], {"b"}) is None
    assert numbered_choice("2", ["a", "b"], {"b"}) == "b"


def test_exact_course_selection_does_not_guess_from_incidental_terms():
    options = [("a", ["CMA USA", "CMA"]), ("b", ["CPA USA", "CPA"])]
    assert explicit_choice("course CMA", options, prefix="course") == "a"
    assert explicit_choice("Explain CMA and CPA differences", options, prefix="course") is None
    assert explicit_choice("course ACCA", options, prefix="course") is None


@pytest.mark.parametrize("paper,overview,mixed", list(product([False, True], repeat=3)))
def test_upload_requires_exactly_one_paper_mode(paper, overview, mixed):
    payload = dict(course_id=uuid4(), curriculum_id=uuid4(), paper_id=uuid4() if paper else None, overview=overview, mixed_papers=mixed)
    if sum((paper, overview, mixed)) == 1:
        Destination(**payload)
    else:
        with pytest.raises(ValidationError):
            Destination(**payload)


def test_file_cannot_bypass_extraction_with_supplied_text():
    destination = dict(courseId=str(uuid4()), curriculumId=str(uuid4()), overview=True)
    with pytest.raises(ValidationError):
        UploadCreate(idempotencyKey="k", title="Book", kind="file", objectKey="staged/source", content="Fake extraction", destination=destination)


def test_mapping_rejects_mixed_papers_and_grant_rejects_extra_paper():
    with pytest.raises(ValidationError):
        AssignmentSave(courseId=uuid4(), curriculumId=uuid4(), sourceVersionId=uuid4(), mixedPapers=True, blockIds=["A"], idempotencyKey="k")
    with pytest.raises(ValidationError):
        EnrollmentAccess(curriculumId=uuid4(), paperIds=[], selectedPaperId=uuid4())
