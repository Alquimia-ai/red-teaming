"""The assistant under test, and the two ways to reach it.

`TargetAssistant` is gaussia's abstract class and the only path to the assistant; gaussia ships no
implementation because a transport adapter belongs with the runtime it talks to. This package ships
exactly two: the Alquimia runtime, which is what a run attacks, and a replay of recorded answers,
which is how a run is rehearsed offline through the same code path. There is no open registry and
no third kind: `ConnectorSpec.kind` names one of these two or is refused by name.

**Building a target here does not make it attackable.** What comes out of `build_target` reaches
the assistant with nothing between them -- no budget, no pacing, no safe-mode gate. The engine wraps
it in its governed door before the first turn, and a guard checks the pipeline knows no other way to
construct one. A target that can be used raw is a governance that can be skipped by accident.
"""

from redteam_target.build import KINDS, UnknownTarget, build_target

__all__ = ["KINDS", "UnknownTarget", "build_target"]
