"""Every transport failure of an attempt, kept so the run can be told what its outage was.

The Profiler counts ungraded exchanges and `conduct` refuses a profile with too many of them: "the
profile would describe an outage rather than the assistant". That refusal is right and, alone, its
diagnosis is not -- it says how many, never what. The ledger is what the governed door writes every
failure into, and its verdict is the typed version of the same refusal: when the failed share is
past the alarm and one kind accounts for most of it, the run dies as that kind, with the record.

Per attempt, on purpose. A relaunch sends every unit marked failed live again, so seeding the
ledger from earlier markers would count the same unit twice; and the one kind that must not wait
for a ratio -- a refused credential -- is aborted by the policy on its first occurrence anyway.
"""

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
