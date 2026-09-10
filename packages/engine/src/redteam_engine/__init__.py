"""Conducting one run against the assistant, governed.

gaussia governs the search; it governs nothing operational. Everything a run needs around the
Profiler and the Exploiter -- the one door to the target with its budget, pacing, retry policy and
safe-mode gate; conversations an attacker steers inside one exchange; every conversation written as
evidence the instant it closes; closed units replayed from the store on a relaunch; the weakness
profile and the exploitation report kept as control artifacts; the attack dataset per replica --
lives here. The runner composes this package with generation; nothing here reads a knowledge base.
"""
