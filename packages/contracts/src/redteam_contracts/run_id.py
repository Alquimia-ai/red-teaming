"""What a run id is allowed to look like, decided once and read by everyone who spells one.

A run id is three things at the same time: a prefix in the store, the name of the job that
attacks on its behalf, and the handle a consumer polls. If each of those applied its own rule,
`Run_1`, `run-1` and `run.1` would be three runs to the store and one job to the platform -- the
second launch would answer "already running" for a run that had never started -- and two long ids
differing in their last character would share one job name.

One rule, the strictest consumer's: a DNS-1123 label short enough that the runner's job prefix
plus the id fits the 63 characters a container or a Job name allows. The gate refuses anything
else before the spec is frozen, and the job name is the id verbatim -- nothing to normalise, so
nothing to fold.
"""

from __future__ import annotations

import re

MAX_LENGTH = 50
"""So `redteam-run-` (12 characters) plus the id stays within a 63-character DNS label."""

RULE = re.compile(rf"^[a-z0-9](?:[a-z0-9-]{{0,{MAX_LENGTH - 2}}}[a-z0-9])?$")
"""Lowercase letters, digits and dashes; starts and ends with a letter or digit."""


def is_valid(run_id: str) -> bool:
    return RULE.fullmatch(run_id) is not None


def check(run_id: str) -> str:
    """The id itself when it follows the rule, or a `ValueError` that says what the rule is.

    Raised rather than normalised: an id that had to be rewritten to fit is an id whose two
    spellings can collide, which is exactly what one rule exists to prevent.
    """
    if not is_valid(run_id):
        raise ValueError(
            f"run id {run_id!r} does not follow the rule: lowercase letters, digits and dashes, "
            f"starting and ending with a letter or digit, at most {MAX_LENGTH} characters. The "
            f"same id names the store prefix and the runner's job, so it is not normalised "
            f"anywhere."
        )
    return run_id
