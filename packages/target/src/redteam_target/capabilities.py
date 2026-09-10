"""The gate that enforces safe mode before the first turn.

Because the attack goes through the assistant's real channel, an assistant that can act -- move
money, book, send messages -- fires **real side effects**. And the category search sends far more
exchanges than the profiler does, so the exposure is not small.

This is the only place in the system that decides how much load somebody else's infrastructure
takes, and the only one that can refuse to start.
"""

from __future__ import annotations

from dataclasses import dataclass


class SafeModeViolation(RuntimeError):
    """Refused before a single turn was sent."""


@dataclass(frozen=True)
class CapabilityGate:
    declared_capabilities: tuple[str, ...]
    safe_mode: bool

    @property
    def can_act(self) -> bool:
        return bool(self.declared_capabilities)

    def assert_may_attack(self) -> None:
        """Called before the first turn. Not a configuration checkbox -- a gate."""
        if self.can_act and not self.safe_mode:
            raise SafeModeViolation(
                f"the target declares {list(self.declared_capabilities)} and safe mode is off. "
                f"Attacking it would fire real side effects, and the search sends far more "
                f"exchanges than the profiler does. This needs a sandbox agreement."
            )
