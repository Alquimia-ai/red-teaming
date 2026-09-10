"""Lint `docs/adr/` against the conventions in `docs/adr/README.md`.

Run locally with `python3 scripts/validate_adrs.py`; CI runs the same file. Under GitHub Actions
every violation is also emitted as a `::error` annotation on the offending line.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import date
from pathlib import Path

ADR_DIR = Path("docs/adr")
README = ADR_DIR / "README.md"
NAME_RE = re.compile(r"^(\d{3})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
TITLE_RE = re.compile(r"^# ADR-(\d{3}): (.+)$")
STATUS_RE = re.compile(
    r"^\*\*Status:\*\* (Accepted|Proposed|Deprecated|Superseded by ADR-\d{3})\s*$"
)
DATE_RE = re.compile(r"^\*\*Date:\*\* (\d{4}-\d{2}-\d{2})\s*$")
NUMBERED_HEADING = re.compile(r"^# \d+[.\s]")
ROW_RE = re.compile(r"^\| \[(\d{3})\]", re.MULTILINE)
REQUIRED = ("## Context", "## Decision", "## Consequences")
GH = os.environ.get("GITHUB_ACTIONS") == "true"


def emit(error: str) -> None:
    print(f"  - {error}", file=sys.stderr)
    if not GH:
        return
    located = re.match(r"^([^:]+):(\d+):\s*(.+)$", error)
    if located:
        print(f"::error file={located[1]},line={located[2]}::{located[3]}", file=sys.stderr)
        return
    plain = re.match(r"^([^:]+):\s*(.+)$", error)
    print(f"::error file={plain[1]}::{plain[2]}" if plain else f"::error::{error}", file=sys.stderr)


def check_file(path: Path, errors: list[str]) -> None:
    fnum = NAME_RE.match(path.name)[1]  # type: ignore[index]
    lines = path.read_text(encoding="utf-8").splitlines()
    text = "\n".join(lines)
    if not lines:
        errors.append(f"{path}: empty file")
        return
    title = TITLE_RE.match(lines[0])
    if not title:
        errors.append(f"{path}:1: title must match `# ADR-NNN: <title>`")
    else:
        if title[1] != fnum:
            errors.append(
                f"{path}:1: ADR number in title ({title[1]}) does not match filename ({fnum})"
            )
        if "—" in title[2]:
            errors.append(f"{path}:1: title contains em-dash; not allowed")
        if "(" in title[2] or ")" in title[2]:
            errors.append(f"{path}:1: title contains parentheses; not allowed")
    has_status = has_date = False
    for i, line in enumerate(lines[:10], 1):
        if line.startswith("**Status:**"):
            has_status = True
            if not STATUS_RE.match(line):
                errors.append(
                    f"{path}:{i}: Status must be Accepted | Proposed | Deprecated | "
                    "Superseded by ADR-NNN"
                )
        if line.startswith("**Date:**"):
            has_date = True
            found = DATE_RE.match(line)
            if not found:
                errors.append(f"{path}:{i}: Date must be ISO YYYY-MM-DD")
            else:
                try:
                    date.fromisoformat(found[1])
                except ValueError:
                    errors.append(f"{path}:{i}: Date {found[1]} is not a valid calendar date")
    if not has_status:
        errors.append(f"{path}: missing **Status:** line")
    if not has_date:
        errors.append(f"{path}: missing **Date:** line")
    for section in REQUIRED:
        if section not in text:
            errors.append(f"{path}: missing required section `{section}`")
    in_mermaid = False
    for i, line in enumerate(lines, 1):
        if NUMBERED_HEADING.match(line):
            errors.append(f"{path}:{i}: numbered top-level heading not allowed (`{line.strip()}`)")
        for artifact in ("contentReference", "oaicite"):
            if artifact in line:
                errors.append(f"{path}:{i}: AI-generation artifact `{artifact}` left in file")
        stripped = line.strip()
        if stripped.startswith("```mermaid"):
            in_mermaid = True
            continue
        if stripped == "```" and in_mermaid:
            in_mermaid = False
            continue
        if in_mermaid and re.search(r"\\(\s|$)", line):
            errors.append(f"{path}:{i}: mermaid line break uses `\\`; use `<br/>` instead")


def main() -> int:
    errors: list[str] = []
    if not ADR_DIR.is_dir():
        print(f"::error::{ADR_DIR} not found", file=sys.stderr)
        return 1
    files = sorted(p for p in ADR_DIR.iterdir() if NAME_RE.match(p.name))
    for path in files:
        check_file(path, errors)

    numbers = [int(NAME_RE.match(p.name)[1]) for p in files]  # type: ignore[index]
    seen: set[int] = set()
    for n in numbers:
        if n in seen:
            errors.append(f"{ADR_DIR}: duplicate ADR-{n:03d}")
        seen.add(n)
    for missing in sorted(set(range(1, max(seen, default=0) + 1)) - seen):
        errors.append(f"{ADR_DIR}: missing ADR-{missing:03d} (numbering must be contiguous)")

    if not README.exists():
        errors.append(f"{README}: file missing")
    else:
        indexed = set(ROW_RE.findall(README.read_text(encoding="utf-8")))
        on_disk = {NAME_RE.match(p.name)[1] for p in files}  # type: ignore[index]
        for absent in sorted(on_disk - indexed):
            errors.append(f"{README}: missing index row for ADR-{absent}")
        for stale in sorted(indexed - on_disk):
            errors.append(f"{README}: index references ADR-{stale} but no file exists")

    if errors:
        print(f"Found {len(errors)} ADR violation(s):", file=sys.stderr)
        for error in errors:
            emit(error)
        return 1
    print(f"OK: {len(files)} ADRs validated against docs/adr/README.md conventions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
