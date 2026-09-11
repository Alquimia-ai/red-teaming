"""Guard: the Exploiter runs in inference mode. This platform must not be able to train.

Roast Me ships two category searches. `AttributeIterationSearch` is training-free: the profile's
attributes are evaluated one at a time, the best-scoring ones are conjoined, the candidate is
refined.
`PolicyGradientSearch` is the paper's headline procedure and trains a category generator.

The platform uses the first. The enforcement is not "the RL module cannot be imported", and it is
worth stating precisely: `PolicyGradientSearch` *does* import without the extra, because its first
four steps are ordinary code and only the fifth needs a GPU. What cannot be imported is the update
step, and what cannot happen is training. That is the guarantee this test pins.

Choosing the training-free search has a cost the docs state plainly and we carry: it has no
published result behind it. It is the default for needing no GPU, not for being the procedure
evaluated.
"""

from __future__ import annotations

import importlib

import pytest

TRAINING_STACK = ["torch", "peft", "accelerate", "trl"]


@pytest.mark.parametrize("module", TRAINING_STACK)
def test_the_training_stack_is_absent(module: str) -> None:
    with pytest.raises(ImportError):
        importlib.import_module(module)


def test_the_policy_update_step_cannot_be_imported() -> None:
    """`ClippedPolicyUpdate` is the only module in the subsystem that imports the training stack."""
    with pytest.raises(ImportError):
        importlib.import_module("gaussia.generators.roastme.searches.policy_update")


def test_the_training_free_search_is_available() -> None:
    module = importlib.import_module("gaussia.generators.roastme.searches.attribute_iteration")
    assert hasattr(module, "AttributeIterationSearch")
