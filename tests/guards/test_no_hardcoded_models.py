"""Guard: no model id, provider URL or embedder name lives in the platform's code.

A model is configuration. In production it comes from the frozen run spec and travels into the
manifest's components, so two runs conducted with different models are never compared by accident.
In tests it comes from a fixture. A module constant naming a model, applied with `setdefault`, is
exactly the shape this test refuses.

It is a rule that erodes on its own if nothing watches it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# A model id is `vendor/name`: two segments of id-ish characters. We only flag it when it is being
# *bound* to a name or passed as a literal default, which is what makes it a hardcoded choice rather
# than a docstring mentioning one.
# Things shaped like `vendor/name` that are emphatically not model ids. A guard that cries wolf is a
# guard somebody switches off, so the exclusions are explicit rather than the pattern being
# loosened.
NOT_A_MODEL = re.compile(
    r"""(?xi)
    ^(?:
        (?: application | text | image | audio | video | multipart | font ) / .+   # MIME types
      | [a-z]+ \+ [a-z]+ /                                                          # vnd.x+json/...
      | [a-z0-9-]+ (?: \. [a-z0-9-]+ )+ / [a-z0-9.-]+                      # k8s label keys
    )$
    """
)
"""A Kubernetes label key is `dns.sub.domain/name`; a model id's vendor is one token with no dot in
it, so a dotted prefix is the platform's namespace and not a vendor's."""

MODEL_LITERAL = re.compile(
    r"""(?x)
    (?: =\s* | \(\s* | ,\s* )        # assigned, or passed positionally / as a default
    (['"])
    (?!https?://)
    (?P<value> [A-Za-z0-9][\w.\-]* / [\w.\-]{2,} )
    \1
    """
)

PROVIDER_URL = re.compile(
    r"""['"]https?://(?:[\w.\-]*\.)?"""
    r"""(openrouter|openai|groq|anthropic|together|fireworks|deepinfra|huggingface)"""
    r"""[\w.\-]*(?:/[^'"]*)?['"]""",
    re.IGNORECASE,
)

SEARCH_ROOTS = ("packages", "apps")
# Fixtures and tests are exactly where a concrete model id belongs.
EXEMPT_PARTS = {"tests", "conftest.py", "fixtures"}


def _sources() -> list[Path]:
    out: list[Path] = []
    for root in SEARCH_ROOTS:
        if not (ROOT / root).is_dir():
            continue
        for path in (ROOT / root).rglob("*.py"):
            if EXEMPT_PARTS & set(path.parts):
                continue
            out.append(path)
    return out


def _offenders(pattern: re.Pattern[str]) -> list[str]:
    hits: list[str] = []
    for path in _sources():
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            code = line.split("#", 1)[0]
            match = pattern.search(code)
            if match and not (
                (value := match.groupdict().get("value")) and NOT_A_MODEL.match(value)
            ):
                rel = path.relative_to(ROOT)
                hits.append(f"{rel}:{lineno}: {line.strip()}")
    return hits


def test_no_model_id_is_bound_in_code() -> None:
    hits = _offenders(MODEL_LITERAL)
    assert not hits, (
        "a model id is bound in the code. Models are configuration: pass the instantiated model "
        "in, or take the id as a parameter. Offending lines:\n  " + "\n  ".join(hits)
    )


def test_no_provider_url_is_bound_in_code() -> None:
    hits = _offenders(PROVIDER_URL)
    assert not hits, (
        "a model-provider URL is bound in the code. Endpoints are configuration. Offending "
        "lines:\n  " + "\n  ".join(hits)
    )


def test_the_pattern_flags_a_model_and_spares_what_only_looks_like_one() -> None:
    """A guard has to be checked to fail, and to not cry wolf."""
    assert _offends('JUDGE = "openai/gpt-4o"')
    assert _offends('model="meta-llama/Llama-3.1-8B",')
    assert not _offends('content_type="application/json"')
    assert not _offends('LABEL = "app.kubernetes.io/name"')
    assert not _offends('LABEL = "red-teaming.alquimia.ai/run-id"')


def _offends(line: str) -> bool:
    match = MODEL_LITERAL.search(line)
    return match is not None and not NOT_A_MODEL.match(match.group("value"))
