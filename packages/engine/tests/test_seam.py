"""What crosses out of conduction is provenance; the measurement of the run is the store's."""

from __future__ import annotations

import inspect

from redteam_engine import conduct


def test_conduction_does_not_export_the_failure_report() -> None:
    """The report is a control artifact and reaches the store through `ControlArtifacts`; what
    crosses out of conduction carries counts, keys and provenance, and no ranking. A reader who
    finds `tau` in the config and a score in the return value would divide one by the other, and
    the manifest would then claim something the run never measured."""
    fields = set(conduct.Conducted.__dataclass_fields__)
    assert "report" not in fields
    assert not {f for f in fields if "failure" in f or "categor" in f}


def test_no_threshold_leaves_the_module() -> None:
    """tau and eta are control. They steer the search and die with the run."""
    source = inspect.getsource(conduct)
    exported = {name for name in dir(conduct) if not name.startswith("_") and name.isupper()}
    assert exported == {"UNGRADED_ALARM_RATIO"}, (
        f"conduction exports {exported}; a search threshold leaving this module is how the "
        f"coverage ends up with a threshold in it"
    )
    assert "tau" not in source.split('"""')[-1]
