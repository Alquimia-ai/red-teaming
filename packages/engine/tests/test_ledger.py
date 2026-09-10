"""The typed version of "the profile would describe an outage": which outage."""

from __future__ import annotations

from http import HTTPStatus

import pytest

from redteam_contracts.failure import RATE_LIMITED, SERVER_ERROR, UNAUTHORIZED, TransportFailure
from redteam_engine.errors import TargetFailure, TargetRateLimited, TargetUnauthorized, error_for
from redteam_engine.ledger import FailureLedger

ALARM = 0.25


def _failure(kind: str, status: HTTPStatus | None = None) -> TransportFailure:
    return TransportFailure(kind=kind, message="said the target", error_type="X", status=status)


def test_one_kind_explaining_the_outage_is_raised_as_that_kind_with_the_record() -> None:
    ledger = FailureLedger()
    for _ in range(4):
        ledger.record(_failure(UNAUTHORIZED, HTTPStatus.UNAUTHORIZED))

    verdict = ledger.verdict(total=4, alarm_ratio=ALARM)

    assert isinstance(verdict, TargetUnauthorized)
    assert verdict.failure.status == HTTPStatus.UNAUTHORIZED
    assert "4 of 4 exchanges failed as 'unauthorized'" in str(verdict)


def test_a_majority_kind_is_enough() -> None:
    ledger = FailureLedger()
    for kind in (RATE_LIMITED, RATE_LIMITED, RATE_LIMITED, SERVER_ERROR):
        ledger.record(_failure(kind))

    assert isinstance(ledger.verdict(total=6, alarm_ratio=ALARM), TargetRateLimited)


def test_mixed_failures_leave_the_generic_refusal_to_speak() -> None:
    """Two kinds at two each: no kind explains it, and `ProfileTooThin` lists the reasons."""
    ledger = FailureLedger()
    for kind in (RATE_LIMITED, RATE_LIMITED, SERVER_ERROR, SERVER_ERROR):
        ledger.record(_failure(kind))

    assert ledger.verdict(total=4, alarm_ratio=ALARM) is None


def test_failures_within_the_alarm_are_not_an_outage() -> None:
    ledger = FailureLedger()
    ledger.record(_failure(UNAUTHORIZED))

    assert ledger.verdict(total=10, alarm_ratio=ALARM) is None
    assert FailureLedger().verdict(total=10, alarm_ratio=ALARM) is None


def test_the_kinds_are_counted_for_the_manifest() -> None:
    ledger = FailureLedger()
    for kind in (RATE_LIMITED, SERVER_ERROR, RATE_LIMITED):
        ledger.record(_failure(kind))
    ledger.recovered = 2

    assert dict(ledger.by_kind()) == {RATE_LIMITED: 2, SERVER_ERROR: 1}
    assert ledger.recovered == 2


def test_an_unregistered_kind_raises_the_base_error_still_carrying_the_record() -> None:
    failure = _failure("something_new")
    raised = error_for(failure)
    assert type(raised) is TargetFailure
    assert raised.failure == failure and raised.kind == "something_new"


def test_a_second_error_class_under_one_kind_is_refused() -> None:
    from redteam_engine.errors import register_error

    class Other(TargetFailure):
        pass

    register_error(UNAUTHORIZED, TargetUnauthorized)
    with pytest.raises(ValueError, match="exactly one exception per kind"):
        register_error(UNAUTHORIZED, Other)


def test_a_second_policy_under_one_kind_is_refused() -> None:
    from redteam_engine.failure_policy import ABORT, RETRY_AS_ASKED, policy_for, register_policy

    register_policy(RATE_LIMITED, RETRY_AS_ASKED)
    with pytest.raises(ValueError, match="exactly one per kind"):
        register_policy(RATE_LIMITED, ABORT)
    assert policy_for("nobody-registered-this").action.value == "give_up"
