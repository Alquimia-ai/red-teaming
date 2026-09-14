"""Track transport failures and recoveries for one attempt.

A dominant failure kind can explain an unusable profile more precisely than its ungraded count.
Do not seed from earlier attempts: retried failures would be counted twice."""

from __future__ import annotations

from collections import Counter

from redteam_contracts.failure import TransportFailure
from redteam_engine.errors import TargetFailure, error_for


class FailureLedger:
    def __init__(self) -> None:
        self.failed: list[TransportFailure] = []
        """Every exchange that ended failed after the policy had its say -- one per unit given up
        on, and the one an abort was raised for."""

        self.recovered = 0
        """Exchanges that failed and then succeeded on a retry. Provenance: how much of the run the
        backoff bought."""

    def record(self, failure: TransportFailure) -> None:
        self.failed.append(failure)

    def by_kind(self) -> Counter[str]:
        return Counter(failure.kind for failure in self.failed)

    def verdict(self, total: int, alarm_ratio: float) -> TargetFailure | None:
        """The typed refusal, when one kind of failure explains the outage.

        None when the failed share is within the alarm, or when the failures are mixed -- then the
        generic thin-profile refusal is the honest one, and its account lists the reasons.
        """
        if not self.failed or len(self.failed) / max(total, 1) <= alarm_ratio:
            return None
        [(kind, count)] = self.by_kind().most_common(1)
        if count * 2 <= len(self.failed):
            return None
        representative = next(failure for failure in self.failed if failure.kind == kind)
        return error_for(
            representative,
            f"{count} of {total} exchanges failed as {kind!r} ({representative.summary()}), so the "
            f"profile would describe an outage of the channel rather than the assistant",
        )
