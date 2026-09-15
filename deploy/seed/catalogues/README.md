# Local catalogue fixtures

Two schema-v2 documents the local stack publishes so a first run has something to generate from. They are a
starting point for an engagement's own catalogue, not a standard: a risk taxonomy *is* what the
evaluation measures, and every engagement is expected to publish its own.

| Document | What it exercises |
|---|---|
| `assistant-baseline.json` | Generic assistant risks, deterministic transforms and an adaptive conversation. Strategies declare their brain requirement independently. |
| `assistant-invented-siblings.json` | The model-driven `contextual_sibling` transform using the run's generator and context. |

Every document embeds the same contract: seven principles with severities that sum to one and
rubrics the control judge is handed unmodified. A run that names several bundles requires them to
carry the same contract.

Publish one file with `redteam catalogue publish <file>`.
