"""The model writes the premise; the check decides whether it counts.

The instruction "do not produce something close to a real name" is a request. What makes it an
invariant is verifying it afterwards -- and the failure it catches is the expensive one, because a
premise one preposition away from a real product makes the assistant retrieve the real one, answer
correctly, and the run charge it with inventing.
"""

from __future__ import annotations

from typing import Any

from gaussia.llm.structured import StructuredOutputStrategy

from redteam_catalogue.contextual import ContextualSiblingTransform, _Sibling, _Siblings
from redteam_contracts.run_spec import ProbeContext

CONTEXT = ProbeContext(language="es-419", domain="banca minorista", tone="clientes")
BOUNDARY = frozenset({"Cuenta Digital Libre", "Pago de Nominas"})


class _Runnable:
    """Answers whatever the scripted turns say, and records what it was asked."""

    def __init__(self, turns: list[dict[str, str]]) -> None:
        self._turns = turns
        self.prompts: list[str] = []

    def invoke(self, messages: list[Any]) -> Any:
        self.prompts.append("\n".join(str(message.content) for message in messages))
        answer = self._turns.pop(0) if self._turns else None
        if answer is None:
            # What a provider answering off-format looks like from here.
            return {"parsed": None}
        return {
            "parsed": _Siblings(
                siblings=[
                    _Sibling(real=real, invented=invented) for real, invented in answer.items()
                ]
            )
        }


class _Binding(StructuredOutputStrategy):  # type: ignore[misc]  # gaussia ships no stubs
    def __init__(self, runnable: _Runnable) -> None:
        self._runnable = runnable

    def bind(self, model: Any, schema: Any) -> Any:
        return self._runnable


def _build(turns: list[dict[str, str]]) -> tuple[ContextualSiblingTransform, _Runnable]:
    runnable = _Runnable(turns)
    built = ContextualSiblingTransform(
        object(),  # type: ignore[arg-type]  # the binding replaces every use of the model
        CONTEXT,
        BOUNDARY,
        structured_output=_Binding(runnable),
    )
    return built, runnable


def test_a_defensible_sibling_is_kept() -> None:
    built, _ = _build([{"Cuenta Digital Libre": "Cuenta Digital Premium"}])
    assert built.apply("Cuenta Digital Libre") == "Cuenta Digital Premium"


def test_a_sibling_that_collides_with_a_real_name_is_rejected() -> None:
    """`Cuenta Digital Libre-2` contains the real name, so the assistant retrieves the real
    product. That is gaussia's own shipped near-miss construction, and it fails this check."""
    built, _ = _build([{"Cuenta Digital Libre": "Cuenta Digital Libre-2"}])
    assert "Cuenta Digital Libre" in built.unresolved
    assert built.apply("Cuenta Digital Libre") == "Cuenta Digital Libre"


def test_a_rejected_batch_is_re_asked_with_what_was_rejected_named() -> None:
    turns = [
        {"Cuenta Digital Libre": "Cuenta Digital Libre-2"},
        {"Cuenta Digital Libre": "Cuenta Digital Premium"},
    ]
    built, runnable = _build(turns)
    assert built.apply("Cuenta Digital Libre") == "Cuenta Digital Premium"
    assert "Cuenta Digital Libre-2" in runnable.prompts[1]


def test_what_never_resolves_is_reported_rather_than_filled_in() -> None:
    """A suffixed fallback substituted here would be the exact false positive the check rejects,
    and it would be invisible."""
    built, _ = _build([{}, {}])
    assert built.unresolved == BOUNDARY


def test_an_off_format_answer_costs_one_attempt_rather_than_raising() -> None:
    built, runnable = _build([])
    assert built.unresolved == BOUNDARY
    assert len(runnable.prompts) >= 1


def test_the_context_reaches_the_prompt() -> None:
    """gaussia's prompts are English and a model answers in the language it is addressed in, so a
    Spanish corpus with no language declared comes back with English names."""
    _, runnable = _build([{"Cuenta Digital Libre": "Cuenta Digital Premium"}])
    assert "es-419" in runnable.prompts[0]
    assert "banca minorista" in runnable.prompts[0]
    assert "clientes" in runnable.prompts[0]


def test_the_real_names_are_sent_so_the_model_can_avoid_them() -> None:
    _, runnable = _build([{"Cuenta Digital Libre": "Cuenta Digital Premium"}])
    for entity in BOUNDARY:
        assert entity in runnable.prompts[0]


def test_one_request_covers_the_whole_boundary() -> None:
    """The cost of the construction lands in one place a run can bound and report, and `apply`
    stays a lookup."""
    built, runnable = _build(
        [{"Cuenta Digital Libre": "Cuenta Digital Premium", "Pago de Nominas": "Pago de Regalias"}]
    )
    assert not built.unresolved
    assert len(runnable.prompts) == 1
