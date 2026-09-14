"""Building the Profiler and the Exploiter.

Everything here is gaussia's; what this module owns is which pieces get chosen. Two of those choices
are decisions rather than defaults, so they live in one place where they can be read:

- The search is always `AttributeIterationSearch`. The Exploiter runs in inference mode, never in
  training mode. The other enforcement is that the training extra is installed in no image, so the
  update step cannot be imported -- the guarantee is "cannot train", not "cannot import", because
  `PolicyGradientSearch` itself imports fine without a GPU.
- `require_logprobs` is on, in the grader the judges package builds. A provider with no usable
  logprobs would send the grader to sampling: five times the cost per grade, temperature forced to
  1.0, and scores quantised to multiples of 1/k. A run that cannot be graded the way it was
  configured should fail and say so.

The cost of the first choice is worth stating rather than burying: the training-free search has no
published result behind it. It is the default for needing no GPU and costing only target calls, not
for being the procedure the paper evaluated.
"""

from __future__ import annotations

from gaussia.core.embedder import Embedder
from gaussia.core.grader import Grader
from gaussia.core.target_assistant import TargetAssistant
from gaussia.generators.roastme.exploiter import Exploiter
from gaussia.generators.roastme.profiler import Profiler
from gaussia.generators.roastme.searches.attribute_iteration import AttributeIterationSearch
from gaussia.generators.roastme.searches.on_profile import JudgeOnProfileFilter
from gaussia.generators.roastme.searches.query_generation import PromptedQueryGenerator
from gaussia.generators.roastme.searches.realism import EmbeddingRealismEstimator
from gaussia.schemas.roastme import BehavioralContract, ExploiterConfig
from langchain_core.language_models.chat_models import BaseChatModel

MAX_ATTRIBUTES = 3
QUERY_ATTEMPTS = 3


def build_profiler(contract: BehavioralContract, target: TargetAssistant) -> Profiler:
    """The Profiler sends probes and grades every response against every principle.

    It reaches no knowledge base -- nothing on its surface accepts a `Document` -- and the weakness
    profile is the only artifact that crosses to the Exploiter.
    """
    return Profiler(contract, target)


def build_exploiter(
    contract: BehavioralContract,
    target: TargetAssistant,
    *,
    generator: BaseChatModel,
    embedder: Embedder,
    realism_prior: list[str],
    config: ExploiterConfig,
    max_attributes: int = MAX_ATTRIBUTES,
) -> Exploiter:
    """The Exploiter searches for categories of realistic interaction that break the assistant
    reproducibly.

    The realism prior is the caller's and an empty one is refused rather than silently making every
    category look realistic. A pool of invented "realistic" queries measures our imagination, so it
    has to come from traffic.
    """
    if not realism_prior:
        raise ValueError(
            "the realism estimator needs a pool of queries real users actually send; an empty pool "
            "would make every category look realistic"
        )
    return Exploiter(
        contract=contract,
        target=target,
        # Inference mode. Never PolicyGradientSearch -- see the module docstring.
        search=AttributeIterationSearch(max_attributes=max_attributes),
        query_generator=PromptedQueryGenerator(model=generator, attempts=QUERY_ATTEMPTS),
        on_profile_filter=JudgeOnProfileFilter(model=generator),
        realism_estimator=EmbeddingRealismEstimator(embedder=embedder, prior=realism_prior),
        config=config,
    )


def grader_components(grader: Grader) -> dict[str, str]:
    """What went into the run, for the manifest.

    Two of the three shipped Exploiter collaborators are gaussia's own construction rather than the
    paper's, so a weak report may be about them rather than about the assistant. Recording which
    implementation ran is what keeps a weak result attributable to the piece that can be swapped.
    """
    return {
        "grader": type(grader).__name__,
        "search": AttributeIterationSearch.__name__,
        "query_generator": PromptedQueryGenerator.__name__,
        "on_profile_filter": JudgeOnProfileFilter.__name__,
        "realism_estimator": EmbeddingRealismEstimator.__name__,
    }
