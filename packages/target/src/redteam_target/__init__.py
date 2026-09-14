"""The Alquimia and recorded-response adapters implementing Gaussia's TargetAssistant.

Raw adapters do not enforce budgets, pacing or safe mode. The engine must wrap them in its
governed target before any live conversation."""

from redteam_target.build import KINDS, UnknownTarget, build_target

__all__ = ["KINDS", "UnknownTarget", "build_target"]
