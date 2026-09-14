"""Bind the declared judge model or an explicitly reported deterministic stand-in.

Control grading uses logprobs rather than silently switching to repeated sampling."""

from __future__ import annotations

from gaussia.core.grader import Grader
from gaussia.graders.logprob import LogprobGrader
from gaussia.schemas.roastme import GraderConfig
from langchain_core.language_models.chat_models import BaseChatModel

from redteam_contracts.run_spec import ModelSpec
from redteam_contracts.serving import ServingPath

# `VIOLATED` is not one token. Against a common tokenizer the answer arrives as `VI`, so a
# vocabulary built on it never matches the first token and every verdict reads wrong. `YES`/`NO`
# survive tokenization whole.
POSITIVE_TOKENS: tuple[str, ...] = ("YES", " YES", "Yes")
NEGATIVE_TOKENS: tuple[str, ...] = ("NO", " NO", "No")

# A reasoning model spends tokens before it answers, and a budget that truncates before the verdict
# produces content with no verdict token in it -- which then reads as a provider without logprobs.
#
# The reasoning length is a random variable with a wide tail, not a property of the input: on one
# input at temperature zero, six calls used between roughly a thousand and two thousand completion
# tokens. A budget is headroom over a distribution rather than a floor over a measurement. 4096 is
# about twice the largest sample seen, and the tail still exists -- which is why a truncated verdict
# is retried and then recorded as ungraded, never allowed to end a chunk. A judge that reasons
# longer declares `reasoning_budget` on its spec.
DEFAULT_REASONING_BUDGET = 4096

# Only reached when logprobs are unavailable AND the caller allowed the fallback. Five draws is the
# smallest sample whose votes are not degenerate.
DEFAULT_FALLBACK_SAMPLES = 5

DEFAULT_TOP_LOGPROBS = 20


def verdict_config(
    *,
    require_logprobs: bool = True,
    reasoning_budget: int = DEFAULT_REASONING_BUDGET,
    fallback_samples: int = DEFAULT_FALLBACK_SAMPLES,
    top_logprobs: int = DEFAULT_TOP_LOGPROBS,
) -> GraderConfig:
    """The verdict surface every judge is asked for.

    `require_logprobs` defaults to True on purpose. Without it, a provider that exposes no usable
    logprobs sends the grader to sampling: five times the cost per grade, `temperature` forced to
    1.0 regardless of configuration, and scores quantised to multiples of 1/k. All of that
    silently. A run that cannot be graded the way it was configured should fail and say so, not
    cost five times more and mean something else.
    """
    return GraderConfig(
        positive_tokens=POSITIVE_TOKENS,
        negative_tokens=NEGATIVE_TOKENS,
        reasoning_budget=reasoning_budget,
        fallback_samples=fallback_samples,
        top_logprobs=top_logprobs,
        require_logprobs=require_logprobs,
    )


def build_grader(model: BaseChatModel, **kwargs: object) -> LogprobGrader:
    """Bind a judge model to the verdict surface.

    The model is built by the caller -- the run spec decides which one in production, a fixture in
    tests. Passing it in rather than naming it is what keeps a measurement's provenance declarable.
    """
    return LogprobGrader(model, verdict_config(**kwargs))  # type: ignore[arg-type]


def grader_for(spec: ModelSpec, api_key: str | None) -> tuple[Grader, ServingPath, str | None]:
    """The instrument a `ModelSpec` declares, and what provenance will say about it.

    One rule for every grader the run builds, so none can drift: a spec naming a provider builds
    that model and grades through the logprob path with retries; a spec naming none -- or no spec
    at all -- grades with the deterministic stand-in and the serving path says `fake`. What was
    asked for is still returned, so provenance can say which judge a stand-in stood in for.

    Returns:
        The grader, where it ran, and the model id it grades as -- `None` when nothing was declared.
    """
    from redteam_contracts.serving import ServingPath as _ServingPath
    from redteam_judges.fake import FakeGrader
    from redteam_judges.models import build_chat_model
    from redteam_judges.retrying import RetryingGrader

    if spec is None or not spec.declares_provider():
        return FakeGrader(), _ServingPath.FAKE, getattr(spec, "model", None)

    budget = {"reasoning_budget": spec.reasoning_budget} if spec.reasoning_budget else {}
    grader = RetryingGrader(build_grader(build_chat_model(spec, api_key=api_key), **budget))
    return grader, spec.serving_path, spec.model
