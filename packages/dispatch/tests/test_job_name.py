"""The job name is the run id behind one prefix. Nothing is normalised, so nothing can fold."""

from __future__ import annotations

import pytest

from redteam_contracts.run_id import MAX_LENGTH
from redteam_dispatch import JOB_PREFIX, job_name


def test_the_name_is_the_id_behind_a_fixed_prefix() -> None:
    assert job_name("run-1") == "redteam-run-run-1"
    assert JOB_PREFIX == "redteam-run-"


def test_two_ids_never_share_a_job() -> None:
    """Folding `Run_1`, `run-1` and `run.1` into one name while the store keeps three prefixes is
    a launch refused as already running for a run that never started."""
    assert job_name("run-1") != job_name("run-2")
    long_a, long_b = "a" * (MAX_LENGTH - 1) + "x", "a" * (MAX_LENGTH - 1) + "y"
    assert job_name(long_a) != job_name(long_b)


def test_the_longest_id_still_fits_a_dns_label() -> None:
    """63 is the label limit and `MAX_LENGTH` is 50 because of it."""
    assert len(job_name("a" * MAX_LENGTH)) <= 63


@pytest.mark.parametrize("outside", ["Run_1", "run.1", "RUN-1", "-run", "run-", "a" * 51, ""])
def test_an_id_outside_the_rule_is_refused_rather_than_rewritten(outside: str) -> None:
    with pytest.raises(ValueError, match="does not follow the rule"):
        job_name(outside)
