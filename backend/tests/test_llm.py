import pytest

from northstar_api.services.llm import (
    ModelUnavailableError,
    _strip_hidden_reasoning,
    validate_embedding_vector,
    validate_embedding_vectors,
)


def test_hidden_reasoning_is_removed_from_visible_model_output() -> None:
    assert _strip_hidden_reasoning("<think>private chain</think>Final answer") == "Final answer"
    assert _strip_hidden_reasoning("Answer<reasoning>private chain</reasoning>") == "Answer"


def test_unterminated_hidden_reasoning_is_not_exposed() -> None:
    assert _strip_hidden_reasoning("Safe answer<think>unfinished private chain") == "Safe answer"


def test_embedding_validation_rejects_corrupt_provider_responses() -> None:
    assert validate_embedding_vector([1, 0], 2) == [1.0, 0.0]
    with pytest.raises(ModelUnavailableError, match="count mismatch"):
        validate_embedding_vectors([[1.0, 0.0]], 2, 2)
    with pytest.raises(ModelUnavailableError, match="dimension mismatch"):
        validate_embedding_vector([1.0], 2)
    with pytest.raises(ModelUnavailableError, match="non-finite"):
        validate_embedding_vector([float("inf"), 1.0], 2)
    with pytest.raises(ModelUnavailableError, match="zero vector"):
        validate_embedding_vector([0.0, 0.0], 2)
