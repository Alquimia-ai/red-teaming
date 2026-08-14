"""Tests for the vitruvio wrapper. No real brain, network, or vitruvio install:
the subprocess runner is faked. Fixtures mirror vitruvio 0.3.x's JSON envelope.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from braintools.vitruvio import Vitruvio, VitruvioError


def envelope(command="query.search", *, ok=True, data=None, warnings=None, error=None):
    return json.dumps(
        {
            "vitruvio": "0.3.0",
            "command": command,
            "ok": ok,
            "data": data,
            "warnings": warnings or [],
            "error": error,
        }
    )


class FakeRunner:
    """Records argv and replays a canned (returncode, stdout, stderr)."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.calls: list[list[str]] = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        return self.returncode, self.stdout, self.stderr


def make(runner) -> Vitruvio:
    return Vitruvio(brain_dir=Path("/tmp/brain"), bin_path="vitruvio", runner=runner)


def test_search_uses_brain_selector_text_and_json():
    runner = FakeRunner(stdout=envelope(data={"matches": [{"block_id": "b1"}]}))
    result = make(runner).search("periodic function", limit=5)

    assert result.data == {"matches": [{"block_id": "b1"}]}
    argv = runner.calls[0]
    assert argv[0] == "vitruvio" and "search" in argv
    assert "--brain" in argv and "/tmp/brain" in argv
    assert "--text" in argv and "periodic function" in argv
    assert "--limit" in argv and "5" in argv
    assert argv[-1] == "--json"  # json flag appended last


def test_search_repeats_memory_type_flag():
    runner = FakeRunner(stdout=envelope(data={"matches": []}))
    make(runner).search("q", memory_types=["semantic", "episodic"])
    argv = runner.calls[0]
    assert argv.count("--memory-type") == 2
    assert "semantic" in argv and "episodic" in argv


def test_init_passes_brain_actor_and_kind():
    runner = FakeRunner(stdout=envelope("brain.init", data={"created": True}))
    make(runner).init(actor="curator", actor_kind="human")
    argv = runner.calls[0]
    assert argv[:2] == ["vitruvio", "brain"] and "init" in argv
    assert "--brain" in argv and "/tmp/brain" in argv
    assert "--actor" in argv and "curator" in argv
    assert "--actor-kind" in argv and "human" in argv


def test_ingest_single_file_with_options():
    runner = FakeRunner(stdout=envelope("ingest.run", data=None))
    make(runner).ingest("./policy.pdf", dry_run=True, proposer="anthropic", subject="policies")
    argv = runner.calls[0]
    assert argv[:2] == ["vitruvio", "ingest"] and "run" in argv
    assert "--path" in argv and "./policy.pdf" in argv
    assert "--proposer" in argv and "anthropic" in argv
    assert "--subject" in argv and "policies" in argv
    assert "--dry-run" in argv


def test_envelope_ok_false_raises_with_code_message_and_hint():
    err = {"code": "BRAIN_NOT_FOUND", "message": "not a brain", "hint": "run brain init"}
    runner = FakeRunner(stdout=envelope(ok=False, error=err))
    with pytest.raises(VitruvioError) as exc:
        make(runner).search("q")
    text = str(exc.value)
    assert "BRAIN_NOT_FOUND" in text and "not a brain" in text and "run brain init" in text
    assert exc.value.error == err


def test_warnings_are_surfaced_on_result():
    runner = FakeRunner(stdout=envelope(data={"ok": 1}, warnings=["partial commit"]))
    result = make(runner).index()
    assert result.warnings == ["partial commit"]


def test_transport_failure_no_envelope_raises_with_stderr():
    runner = FakeRunner(returncode=2, stdout="", stderr="usage: bad flag")
    with pytest.raises(VitruvioError) as exc:
        make(runner).index()
    assert "usage: bad flag" in str(exc.value)


def test_empty_stdout_success_returns_none():
    runner = FakeRunner(stdout="   ")
    assert make(runner).index().data is None


def test_browse_is_not_json_and_returns_code():
    runner = FakeRunner(returncode=0)
    code = make(runner).browse()
    assert code == 0
    assert "--json" not in runner.calls[0]
    assert "browse" in runner.calls[0] and "--brain" in runner.calls[0]


def test_verify_calls_brain_verify():
    runner = FakeRunner(stdout=envelope("brain.verify", data={"verified": True}))
    assert make(runner).verify().data == {"verified": True}
    argv = runner.calls[0]
    assert argv[:2] == ["vitruvio", "brain"] and "verify" in argv


def test_push_builds_dist_push_with_reference_tag_and_local():
    runner = FakeRunner(stdout=envelope("dist.push", data={"digest": "sha256:abc"}))
    make(runner).push(reference="ghcr.io/org/brain", tag="v1", local="/tmp/reg")
    argv = runner.calls[0]
    assert argv[:2] == ["vitruvio", "dist"] and "push" in argv
    assert "--reference" in argv and "ghcr.io/org/brain" in argv
    assert "--tag" in argv and "v1" in argv
    assert "--local" in argv and "/tmp/reg" in argv


def test_pull_builds_dist_pull_and_can_be_anonymous():
    runner = FakeRunner(stdout=envelope("dist.pull", data={}))
    make(runner).pull(reference="ghcr.io/org/brain", tag="v1", anonymous=True)
    argv = runner.calls[0]
    assert argv[:2] == ["vitruvio", "dist"] and "pull" in argv
    assert "--anonymous" in argv


def test_config_set_builds_config_set():
    runner = FakeRunner(stdout=envelope("config.set", data={}))
    make(runner).config_set("registry.reference", "ghcr.io/org/brain")
    argv = runner.calls[0]
    assert argv[:3] == ["vitruvio", "config", "set"]
    assert "registry.reference" in argv and "ghcr.io/org/brain" in argv


def test_extract_digest_reads_common_shapes():
    from braintools.cli import _extract_digest

    assert _extract_digest({"digest": "sha256:abc"}) == "sha256:abc"
    assert _extract_digest({"snapshot": {"digest": "sha256:def"}}) == "sha256:def"
    assert _extract_digest({"nothing": 1}) is None
    assert _extract_digest("not a dict") is None


def test_subject_for_derives_from_immediate_subdir():
    from braintools.cli import _subject_for

    root = Path("/repo/docs/sources")
    assert _subject_for(root / "roastme" / "spec.md", root, "misc") == "roastme"
    assert _subject_for(root / "sparring" / "2026-08-14-leo-x.md", root, "misc") == "sparring"
    assert _subject_for(root / "loose.md", root, "misc") == "misc"  # no subdir -> default


def test_slugify_is_filesystem_safe():
    from braintools.cli import _slugify

    assert _slugify("Prompt Injection via Tool Args!") == "prompt-injection-via-tool-args"
    assert _slugify("  spaces  &  symbols  ") == "spaces-symbols"
    assert _slugify("") == "untitled"
