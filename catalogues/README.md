# Catalogues

Default RoastMe catalogues for red teaming Alquimia assistants, grouped into **families**, one
folder per family. Each family is a taxonomy of a single kind of risk, and it grows on its own so
that adding one never disturbs another.

Every family carries its risks as per-plugin YAML files under `risks/`, which are the source, and
a `build.py` that assembles them into the schema-v2 JSON a run publishes. The JSON is generated and
never edited by hand, so the two cannot drift.

How a run is turned into a red, yellow or green verdict is the same across every family and lives
in [METHODOLOGY.md](METHODOLOGY.md).

How the families map onto OWASP, NIST and other recognised frameworks, and where the gaps are,
is in [FRAMEWORKS.md](FRAMEWORKS.md).

## Families

| Family | What it tests | State |
|---|---|---|
| [security-owasp](security-owasp/) | The agent-security risks of the OWASP AI Agent Security Cheat Sheet | shipped |
| [sycophancy](sycophancy/) | The agent agreeing with a false premise, caving under pressure, or blessing a risky plan | shipped |
| [privacy](privacy/) | The agent mishandling the user's own sensitive data: taking secrets it should not, exposing or reusing them |  shipped |
| [human-ai-configuration](human-ai-configuration/) | The agent passing for a human, or claiming an authority it does not have | shipped |
| [bias](bias/) | The agent treating a person differently on a protected attribute irrelevant to the request | shipped |
| [harmful-content](harmful-content/) | The agent producing content that could cause harm: dangerous instructions, harm in disguise, hate | shipped |
| [specialized-advice](specialized-advice/) | The agent diagnosing, dosing, deciding a legal case or picking a financial move for the user's own situation | draft |
| [self-harm](self-harm/) | The agent missing a user's disclosure of self-harm, or giving the means when asked | draft |
| [fraud-enablement](fraud-enablement/) | The agent helping launder or hide money, forge documents or write scams | draft |

The families come from surveying other red-team taxonomies (promptfoo, NIST). They are added one
at a time, so the set here is always one we have reviewed rather than a dump of everything a survey
lists. The next candidates, from that survey, are robustness under malformed input, and toxicity or
harmful-content refusal.

## A family is a contract

A run over several catalogues requires them to carry the same contract, so two families cannot be
run in one pass as they stand. Each family is published and run on its own, and its verdict is read
against its own contract.
