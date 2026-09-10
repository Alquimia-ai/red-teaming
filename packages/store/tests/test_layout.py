"""The layout is the contract every component reads. It gets tested like one."""

from __future__ import annotations

import pytest

from redteam_store import layout

RUN = "run-01HX7Z"
ATTACK = "a1b2c3d4e5f60718293a4b5c6d7e8f90"


def test_the_paths_of_one_run() -> None:
    assert layout.spec(RUN) == f"runs/{RUN}/spec.json"
    assert layout.probes(RUN) == f"runs/{RUN}/probes.json"
    assert layout.category(RUN, "cat-7") == f"runs/{RUN}/categories/cat-7.json"
    assert layout.trace(RUN, ATTACK, 0) == f"runs/{RUN}/traces/{ATTACK}/0.jsonl.zst"
    assert layout.trace_failure(RUN, ATTACK, 2) == f"runs/{RUN}/traces/{ATTACK}/2.failed"
    assert layout.dataset(RUN) == f"runs/{RUN}/dataset.json"
    assert layout.profile(RUN) == f"runs/{RUN}/profile.json"
    assert layout.exploit(RUN) == f"runs/{RUN}/exploit.json"
    assert layout.conduction(RUN) == f"runs/{RUN}/conduction.json"
    assert layout.session(RUN, "exploit") == f"runs/{RUN}/sessions/exploit.json"
    assert layout.searched(RUN) == f"runs/{RUN}/searched.json"
    assert layout.parse_spec_key(layout.spec(RUN)) == RUN
    assert layout.parse_spec_key(layout.probes(RUN)) is None
    assert layout.manifest(RUN) == f"runs/{RUN}/manifest.json"
    assert layout.blob("a" * 64) == f"blobs/{'a' * 64}"


def test_nothing_in_the_layout_is_a_cache() -> None:
    """Every key is written once. A key that would be rewritten has no place here."""
    assert not hasattr(layout, "progress")
    assert not hasattr(layout, "ephemeral")


def test_a_trace_key_round_trips() -> None:
    """Resumption is a set difference over listed keys, so the key has to be readable back into the
    plan's own coordinates."""
    key = layout.trace(RUN, ATTACK, 7)
    assert layout.parse_trace_key(key) == (RUN, ATTACK, 7)


@pytest.mark.parametrize(
    "key",
    [
        f"runs/{RUN}/traces/{ATTACK}/2.failed",  # a marker is not a trace
        f"runs/{RUN}/spec.json",
        f"blobs/{'a' * 64}",
        "nonsense",
    ],
)
def test_a_non_trace_key_parses_to_nothing(key: str) -> None:
    assert layout.parse_trace_key(key) is None


@pytest.mark.parametrize("evil", ["../escape", "a/b", "", "." * 3, "x" * 200, "with space"])
def test_a_key_cannot_climb_out_of_its_prefix(evil: str) -> None:
    with pytest.raises(ValueError, match="unsafe run id"):
        layout.spec(evil)


def test_a_digest_has_to_look_like_one() -> None:
    with pytest.raises(ValueError, match="not a hex digest"):
        layout.blob("../../etc/passwd")
    with pytest.raises(ValueError, match="not a hex digest"):
        layout.blob("NOTHEX" * 8)


def test_a_negative_replica_is_refused() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        layout.trace(RUN, ATTACK, -1)


def test_versions_sort_lexicographically_in_the_order_they_were_written() -> None:
    """Listing a bucket gives lexicographic order. Zero-padding is what makes that the real order --
    without it v10 sorts before v2 and "the newest" reads off the wrong key."""
    keys = [layout.catalogue("base", v) for v in (1, 2, 10, 100)]
    assert keys == sorted(keys)
    assert layout.parse_catalogue_key(keys[2]) == ("base", 10)


@pytest.mark.parametrize(
    ("sidecar", "kind"),
    [
        (layout.catalogue_contract, "contract"),
        (layout.catalogue_grounding, "grounding"),
        (layout.catalogue_delivery, "delivery"),
    ],
)
def test_a_sidecar_sits_beside_its_catalogue_version_and_is_not_one(
    sidecar: object, kind: str
) -> None:
    """Versioned with the catalogue it describes, so a later version that renames a strategy or a
    principle cannot leave a sidecar pointing at nothing -- and invisible to the version listing."""
    assert callable(sidecar)
    assert sidecar("base", 3) == f"catalogues/base/v00003.{kind}.json"
    assert layout.parse_catalogue_key(sidecar("base", 3)) is None
    assert layout.parse_catalogue_key("catalogues/base/v00003.json") == ("base", 3)
    with pytest.raises(ValueError, match="start at 1"):
        sidecar("base", 0)


def test_an_attempt_s_marker_and_its_failure_record_share_the_attempt_id() -> None:
    """The status reads `failed` only while the newest attempt is the one that died, so both keys
    have to read back into the same coordinate -- and neither may parse as the other."""
    attempt = "20260903T170000.000000Z-abc123"

    assert layout.attempt(RUN, attempt) == f"runs/{RUN}/attempts/{attempt}.json"
    assert layout.parse_attempt_key(layout.attempt(RUN, attempt)) == (RUN, attempt)
    assert layout.parse_failure_key(layout.failure(RUN, attempt)) == (RUN, attempt)
    assert layout.parse_attempt_key(layout.failure(RUN, attempt)) is None
    assert layout.parse_failure_key(layout.attempt(RUN, attempt)) is None
    assert layout.parse_attempt_key(layout.manifest(RUN)) is None
