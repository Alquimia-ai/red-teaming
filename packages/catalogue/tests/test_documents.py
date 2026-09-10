"""A corpus that cannot ground the run it was pulled for says so, instead of degrading."""

from __future__ import annotations

import pytest

from redteam_catalogue.documents import UngroundableCorpus, require_groundable, to_documents
from redteam_contracts.kb import Passage

PROSE = Passage(id="b1", content="Coverage begins on the first day of the month.", structured=False)
ENUMERABLE = Passage(id="b2", content="Cuenta Digital Libre", structured=True)


def test_passages_cross_into_documents_unchanged() -> None:
    [document] = to_documents([ENUMERABLE])
    assert (document.id, document.content, document.structured) == ("b2", ENUMERABLE.content, True)


def test_an_empty_corpus_is_refused_rather_than_producing_hookless_probes() -> None:
    """The degraded path is silent: hookless probes are legitimate for a black-box run, so nothing
    downstream can tell a mistagged brain from a run that asked for no base at all."""
    with pytest.raises(UngroundableCorpus, match="no passages"):
        require_groundable([], needs_boundary=True)


def test_an_all_prose_corpus_is_refused_when_an_engine_decides_absence() -> None:
    with pytest.raises(UngroundableCorpus, match="enumerable"):
        require_groundable([PROSE], needs_boundary=True)


def test_an_all_prose_corpus_is_fine_when_nothing_claims_absence() -> None:
    """A run composing only engines that twist a stated fact needs no boundary, and prose is
    exactly what those read."""
    require_groundable([PROSE], needs_boundary=False)


def test_one_enumerable_passage_is_enough() -> None:
    require_groundable([PROSE, ENUMERABLE], needs_boundary=True)
