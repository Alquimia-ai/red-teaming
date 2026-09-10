# Seed catalogue bundles

Two bundles the local stack publishes so a first run has something to generate from. They are a
starting point for an engagement's own catalogue, not a standard: a risk taxonomy *is* what the
evaluation measures, and every engagement is expected to publish its own.

| Bundle | What it exercises |
|---|---|
| `assistant-baseline/` | The generic risks any deployed assistant carries: invented products (`swap_token`), contradicted figures and dates (`shift_figure`, `shift_date`), configuration disclosure (one static turn and one four-turn conversation steered by the `crescendo` attacker), acting for somebody else, refusing a handoff, misrepresenting itself. Half its strategies need a knowledge base; the other half stand alone, so it works for both grounded and black-box runs. |
| `assistant-invented-siblings/` | The model-driven construction: `contextual_sibling` invents a product that reads like a real one, with the run's declared language, domain and tone. Needs a run that declares a `generator` and a `context`; without them generation refuses by name. |

Every bundle carries the same `contract.json`: seven principles with severities that sum to one and
rubrics the control judge is handed unmodified. A run that names several bundles requires them to
carry the same contract.

Author a bundle with the `/catalogue` skill and publish it with `redteam catalogue publish`.
