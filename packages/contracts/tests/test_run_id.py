"""One rule for a run id, read by the store, the dispatcher and the gate."""

from __future__ import annotations

import pytest

from redteam_contracts.run_id import MAX_LENGTH, check, is_valid


@pytest.mark.parametrize(
    "run_id", ["r", "run-1", "e2e-pytest-1757260000", "0", "a" * MAX_LENGTH, "a-b-c-d-9"]
)
def test_what_follows_the_rule(run_id: str) -> None:
    assert is_valid(run_id)
    assert check(run_id) == run_id


@pytest.mark.parametrize(
    ("run_id", "why"),
    [
        ("Run-1", "case would fold on a store that folds case"),
        ("run_1", "an underscore is not in a DNS label"),
        ("run.1", "a dot is not in a DNS label"),
        ("-run", "a label starts with a letter or digit"),
        ("run-", "a label ends with a letter or digit"),
        ("a" * (MAX_LENGTH + 1), "the job prefix plus the id would exceed 63"),
        ("", "empty"),
        ("../escape", "a path"),
        ("with space", "a space"),
    ],
)
def test_what_breaks_the_rule_is_refused_naming_it(run_id: str, why: str) -> None:
    assert not is_valid(run_id), why
    with pytest.raises(ValueError, match="does not follow the rule") as refused:
        check(run_id)
    assert str(MAX_LENGTH) in str(refused.value)


def test_the_job_prefix_and_the_longest_id_fit_a_dns_label() -> None:
    assert len("redteam-run-") + MAX_LENGTH <= 63
