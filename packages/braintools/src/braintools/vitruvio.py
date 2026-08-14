"""Thin wrapper over the vitruvio brain-runtime CLI (v0.3.x).

vitruvio is authoritative over the brain; this module never reimplements brain
mechanics. It shells out to the ``vitruvio`` executable and, for data commands, passes
``--json`` and parses vitruvio's JSON *envelope*::

    {"vitruvio": "0.3.0", "command": "query.search",
     "ok": true, "data": {...}, "warnings": [...], "error": null}

Note that vitruvio reports failures **inside** the envelope (``ok: false`` with a
structured ``error``) while still exiting 0 — so success is decided by ``ok``, not by
the process return code. ``--json`` also implies ``--quiet``, so stdout is pure JSON.

The brain is selected with the global ``--brain <name|path>`` option, which every
command accepts.

The subprocess runner is injectable (``runner`` argument) so tests can drive the
wrapper against a fake without a real brain, network, or vitruvio install.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config


@dataclass(frozen=True)
class CompletedCall:
    """The raw result of one vitruvio invocation."""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class VitruvioError(RuntimeError):
    """A vitruvio call failed — either at the transport level (non-zero exit with no
    envelope) or inside the envelope (``ok: false``)."""

    def __init__(
        self,
        message: str,
        *,
        call: CompletedCall | None = None,
        error: dict[str, Any] | None = None,
    ):
        self.call = call
        self.error = error  # the envelope's structured error, if any
        super().__init__(message)

    @classmethod
    def from_envelope(cls, error: dict[str, Any], call: CompletedCall) -> VitruvioError:
        code = error.get("code", "ERROR")
        msg = error.get("message", "vitruvio reported a failure")
        hint = error.get("hint")
        text = f"{code}: {msg}"
        if hint:
            text += f"\nhint: {hint}"
        return cls(text, call=call, error=error)


# A runner takes an argv and returns (returncode, stdout, stderr). Injectable for tests.
Runner = Callable[[Sequence[str]], tuple[int, str, str]]


def _default_runner(argv: Sequence[str]) -> tuple[int, str, str]:
    import subprocess

    proc = subprocess.run(  # noqa: S603 - argv is composed from our own commands
        list(argv),
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


@dataclass
class Result:
    """A successful envelope: its ``data`` plus any non-fatal warnings."""

    data: Any
    warnings: list[Any] = field(default_factory=list)


class Vitruvio:
    """A handle to a specific brain, driven through the vitruvio CLI."""

    def __init__(
        self,
        brain_dir: Path | None = None,
        bin_path: str | None = None,
        runner: Runner | None = None,
    ):
        self.brain_dir = brain_dir or config.brain_dir()
        self.bin_path = bin_path or config.vitruvio_bin()
        self._run = runner or _default_runner

    # -- low level -----------------------------------------------------------

    def _brain_args(self) -> list[str]:
        return ["--brain", str(self.brain_dir)]

    def _call(self, args: Sequence[str], *, json_out: bool) -> CompletedCall:
        argv = [self.bin_path, *args]
        if json_out:
            argv.append("--json")
        returncode, stdout, stderr = self._run(argv)
        return CompletedCall(tuple(argv), returncode, stdout, stderr)

    def run(self, args: Sequence[str]) -> Result:
        """Run a data command with ``--json``, validate the envelope, return a Result."""
        call = self._call(args, json_out=True)
        stripped = call.stdout.strip()
        if not stripped:
            if call.returncode != 0:
                raise VitruvioError(
                    call.stderr.strip() or f"vitruvio exited {call.returncode}",
                    call=call,
                )
            return Result(data=None)
        try:
            envelope = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise VitruvioError(
                f"could not parse vitruvio JSON envelope: {stripped[:200]}", call=call
            ) from exc
        if isinstance(envelope, dict) and not envelope.get("ok", True):
            error = envelope.get("error") or {"message": "vitruvio reported ok: false"}
            raise VitruvioError.from_envelope(error, call)
        data = envelope.get("data") if isinstance(envelope, dict) else envelope
        warnings = envelope.get("warnings", []) if isinstance(envelope, dict) else []
        return Result(data=data, warnings=warnings)

    def run_data(self, args: Sequence[str]) -> Any:
        """Convenience: run a data command and return just its ``data``."""
        return self.run(args).data

    def run_interactive(self, args: Sequence[str]) -> int:
        """Run a command that has no ``--json`` mode (e.g. ``browse``)."""
        call = self._call(args, json_out=False)
        if call.returncode != 0:
            raise VitruvioError(
                call.stderr.strip() or f"vitruvio exited {call.returncode}", call=call
            )
        return call.returncode

    # -- brain operations ----------------------------------------------------

    def init(self, *, actor: str | None = None, actor_kind: str | None = None) -> Result:
        args = ["brain", "init", *self._brain_args()]
        if actor:
            args += ["--actor", actor]
        if actor_kind:
            args += ["--actor-kind", actor_kind]
        return self.run(args)

    def ingest(
        self,
        source: Path | str,
        *,
        dry_run: bool = False,
        proposer: str | None = None,
        media_type: str | None = None,
        subject: str | None = None,
    ) -> Result:
        args = ["ingest", "run", *self._brain_args(), "--path", str(source)]
        if proposer:
            args += ["--proposer", proposer]
        if media_type:
            args += ["--media-type", media_type]
        if subject:
            args += ["--subject", subject]
        if dry_run:
            args.append("--dry-run")
        return self.run(args)

    def index(self) -> Result:
        return self.run(["index", "build", *self._brain_args()])

    def search(
        self,
        text: str,
        *,
        limit: int | None = None,
        memory_types: Sequence[str] | None = None,
        mode: str | None = None,
        content: bool = False,
    ) -> Result:
        args = ["search", *self._brain_args(), "--text", text]
        if limit is not None:
            args += ["--limit", str(limit)]
        for mt in memory_types or []:
            args += ["--memory-type", mt]
        if mode:
            args += ["--mode", mode]
        if content:
            args.append("--content")
        return self.run(args)

    def browse(self, memory_type: str | None = None) -> int:
        args = ["browse", *self._brain_args()]
        if memory_type:
            args += ["--memory-type", memory_type]
        return self.run_interactive(args)
