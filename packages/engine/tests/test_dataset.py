"""One session per replica, every turn keeping gaussia's record, and the record surviving the
store."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest
from gaussia.schemas.roastme import GradedOutcome, KnowledgeHook, PrincipleGrade, Probe

from redteam_contracts.plan import PlannedProbe, WorkUnit, expand
from redteam_engine.dataset import (
    EXPLOIT_SESSION,
    RoastDataset,
    RoastSessions,
    as_roast,
    roast_dataset,
)
from redteam_engine.outcomes import UnitOutcome

COMMON = {"run_id": "run", "assistant_id": "asst-1", "context": "banca", "language": "es-419"}


@dataclass
class _Result:
    outcomes: list[GradedOutcome]
    probes: list[Probe] = field(default_factory=list)
    n_ungraded: int = 0


def _dataset(
    units: list[WorkUnit], probes: list[Probe], result: _Result, report: object, **kwargs: str
) -> RoastSessions:
    return roast_dataset(
        [UnitOutcome(u, p, o) for u, p, o in zip(units, probes, result.outcomes, strict=True)],
        report,
        **kwargs,
    )


def _probe(pid: str, strategy: str, entity: str, *, doc: int) -> Probe:
    return Probe(
        id=pid,
        query=f"q {entity}?",
        strategy=strategy,
        plugin="invented-entity",
        attrs=["a"],
        hook=KnowledgeHook(
            kind="product", references=entity, doc=doc, how="x", principle="no_invention"
        ),
    )


def _grade(violation: float) -> PrincipleGrade:
    return PrincipleGrade(
        principle="no_invention", score=violation, grader="fake", method="fake-marker", model=None
    )


def _outcome(probe: Probe, violation: float, response: str = "an answer") -> GradedOutcome:
    return GradedOutcome(
        probe_id=probe.id,
        response=response,
        grades=[_grade(violation)],
        violation=violation,
        evidence_available=True,
        scoreable=True,
    )


def _units(probes: list[Probe], replicas: int) -> list[WorkUnit]:
    """The units in plan order -- sorted by `(attack_id, replica_idx)` -- which is the order the
    engine hands the Profiler and the order the recorder maps the exchanges by."""
    planned = [PlannedProbe(probe_id=p.id, plugin=p.plugin, strategy=p.strategy) for p in probes]
    return list(expand("run", planned, {"c": "u"}, replicas).units)


def _handed(probes: list[Probe], units: list[WorkUnit]) -> list[Probe]:
    """What the Profiler was given: one probe per unit, the same probe once per replica."""
    by_id = {p.id: p for p in probes}
    return [by_id[unit.probe_id] for unit in units]


def test_each_replica_carries_its_own_outcome() -> None:
    """Every replica of a probe shares its `probe_id`, so keying outcomes by id would collapse N
    graded answers into the last one and every session would carry it. The match is positional."""
    plain = _probe("x", "ask-plain", "Plan Uno", doc=1)
    units = _units([plain], replicas=2)
    handed = _handed([plain], units)
    outcomes = [
        _outcome(plain, 0.0, response=f"the answer replica {unit.replica_idx} got")
        for unit in units
    ]

    roast = _dataset(units, handed, _Result(outcomes, handed), None, **COMMON)

    answers = {d.session_id: d.conversation[0].assistant for d in roast.sessions}
    assert answers == {
        "run:r0": "the answer replica 0 got",
        "run:r1": "the answer replica 1 got",
    }, "the replicas collapsed onto one outcome"
    assert all(d.language == "es-419" and d.assistant_id == "asst-1" for d in roast.sessions)


def test_a_misaligned_outcome_list_is_refused_rather_than_mispaired() -> None:
    plain = _probe("x", "ask-plain", "Plan Uno", doc=1)
    units = _units([plain], replicas=2)
    handed = _handed([plain], units)
    with pytest.raises(ValueError):
        _dataset(units, handed, _Result([_outcome(plain, 0.0)], handed), None, **COMMON)


def test_every_turn_keeps_gaussia_s_record_and_id() -> None:
    fake = _probe("f", "ask-fake", "Plan Oro Plus", doc=0)
    control = _probe("c", "control", "Plan Oro", doc=1)
    units = _units([fake, control], replicas=1)
    handed = _handed([fake, control], units)
    outcomes = [_outcome(p, 1.0 if p.id == "f" else 0.0) for p in handed]

    roast = _dataset(units, handed, _Result(outcomes, handed), None, **COMMON)

    [session] = roast.sessions
    by_id = {turn.qa_id: turn for turn in session.conversation}
    assert set(by_id) == {"f", "c"}, "gaussia's ids, untouched"
    assert by_id["f"].roast.violation == 1.0 and by_id["c"].roast.violation == 0.0
    assert by_id["f"].roast.provenance.strategy == "ask-fake"
    assert by_id["f"].roast.provenance.hook is not None
    assert by_id["f"].roast.provenance.hook.references == "Plan Oro Plus"
    assert all(t.ground_truth_assistant == "" for t in session.conversation), (
        "a trap has no correct answer; gaussia writes none and nothing here invents one"
    )


def test_the_record_survives_the_round_trip_through_json() -> None:
    """gaussia's `Dataset` declares `list[Batch]`, so a session read back from the store would
    validate each turn as a plain `Batch` and drop the record. The narrowed type is what keeps
    it."""
    plain = _probe("x", "ask-plain", "Plan Uno", doc=1)
    units = _units([plain], replicas=1)
    roast = _dataset(units, [plain], _Result([_outcome(plain, 0.5)], [plain]), None, **COMMON)

    [session] = roast.sessions
    reloaded = RoastDataset.model_validate(json.loads(session.model_dump_json()))

    assert reloaded == session
    assert reloaded.conversation[0].roast.violation == 0.5
    assert reloaded.conversation[0].roast.rationale[0].method == "fake-marker"


def test_the_search_s_session_is_appended_when_the_search_found_something() -> None:
    from gaussia.schemas.roastme import (
        Category,
        CategoryEvaluation,
        FailureReport,
        RecordProvenance,
        RoastDatasetRecord,
    )

    plain = _probe("x", "ask-plain", "Plan Uno", doc=1)
    units = _units([plain], replicas=1)
    grade = _grade(1.0)
    evaluation = CategoryEvaluation(
        category=Category(attributes=["asks about limits"], provenance=["no_invention"]),
        queries=["what is the limit?"],
        responses=["exactly 4,500"],
        violations=[1.0],
        on_profile=[True],
        realism_gap=0.0,
        score=1.0,
        passed=True,
        n=1,
        rationale=[[grade]],
        dropped_attributes=[],
    )
    record = RoastDatasetRecord(
        query="what is the limit?",
        response="exactly 4,500",
        violation=1.0,
        principles_charged=["no_invention"],
        rationale=[grade],
        evidence=None,
        provenance=RecordProvenance(category=["asks about limits"]),
    )
    report = FailureReport(
        categories=[evaluation], queries_over_threshold=[record], components={"search": "x"}
    )

    roast = _dataset(units, [plain], _Result([_outcome(plain, 0.0)], [plain]), report, **COMMON)

    assert [d.session_id for d in roast.sessions] == ["run:r0", f"run:{EXPLOIT_SESSION}"]
    search = roast.sessions[-1]
    assert search.conversation[0].roast.provenance.category == ["asks about limits"]
    assert search.conversation[0].roast.evidence_available is False

    empty = report.model_copy(update={"queries_over_threshold": []})
    roast = _dataset(units, [plain], _Result([_outcome(plain, 0.0)], [plain]), empty, **COMMON)
    assert [d.session_id for d in roast.sessions] == ["run:r0"], "nothing over tau, no session"


def test_a_turn_without_a_record_is_refused_rather_than_widened() -> None:
    from gaussia.schemas.common import Batch, Dataset

    bare = Dataset(
        session_id="s",
        assistant_id="a",
        context="c",
        conversation=[Batch(qa_id="q", query="q", assistant="a", ground_truth_assistant="")],
    )
    with pytest.raises(TypeError, match="no roast record"):
        as_roast(bare)
