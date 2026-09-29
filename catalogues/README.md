# Security catalogue

A default catalogue for the agent-security risks of the
[OWASP AI Agent Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html),
as one schema-v2 document: `owasp-agent-security.json`.

It is a starting point, not a standard. A contract is what counts as failure, so every engagement
activates the risks it cares about, rewrites the rubrics it disagrees with, and publishes its own.

- **Publishing and running it** → [RUNNING.md](RUNNING.md)
- **The risks we held back** → [deferred/README.md](deferred/README.md)

## What it covers

8 principles, 8 plugins, 83 strategies (61 attacks, 22 controls), every probe in Spanish and English.

| OWASP risk | Plugin |
|---|---|
| Prompt Injection (Direct & Indirect) | `prompt-injection` |
| Goal Hijacking | `goal-hijacking` |
| Sensitive Data Exposure | `configuration-disclosure` **+** `third-party-data` |
| Data Exfiltration | `data-exfiltration` |
| Tool Abuse & Privilege Escalation | `tool-abuse` |
| Excessive Autonomy **+** High-Impact Action Abuse | `high-impact-actions` |
| Decision and Approval Manipulation | `approval-manipulation` |

Two rows do not map one to one. **Sensitive Data Exposure is two plugins**: leaking the agent's
own configuration and leaking somebody else's data are different obligations, and one rubric over
both gives a rate nobody can read. **Excessive Autonomy and High-Impact Action Abuse are one**:
they differ by intent, which a black-box probe cannot see, and both show up as the same thing,
an agent committing to something irreversible with no confirmation.

## What it does not cover

| Risk | Why |
|---|---|
| Memory Poisoning | deferred: fails in memory carried to later sessions, which the answer cannot show |
| Denial of Wallet | deferred: fails in the bill, which the answer cannot show |
| Cascading Failures, AI Console Malicious Configuration, Supply Chain | architecture controls; a plugin would report zero on every run, and not because the agent is safe |

A report over this catalogue must say these were **not measured**, never that they came out clean.

## Review these before a run

Every probe is domain-neutral and runs against any agent. Three plugins measure more when adapted
to the agent first, and one has a precondition.

| Plugin | Review first? | Why |
|---|---|---|
| `prompt-injection`, `configuration-disclosure`, `third-party-data` | no | the failure is the same in any domain |
| `data-exfiltration` | read with the channel | the markdown-image probe only fires where markdown renders |
| `goal-hijacking` | recommended | the rubric decides what "out of scope" is |
| `tool-abuse` | recommended | a refusal may mean "cannot", not "will not" |
| `high-impact-actions`, `approval-manipulation` | **required** | they assume the agent can act, or has an approval step |

Adapting runs in two directions: push the **attacks** further outside the agent's scope, so a
refusal is earned, and pull the **controls** further inside it, so a failing control tells you the
run was aimed at the wrong surface.

## How to read and change it

- **One plugin, one principle.** Strategies vary how an attack is delivered, never which rule it
  breaks, so every probe under a plugin is judged against one definition of failure.
- **The rubric is the measurement.** It is the only text the judge reads, and the judge answers
  with one token. Each rubric states the rule, what does not count, and ends in a YES/NO question.
  Rewrite any that does not match what your agent is held to; keep it one rule.
- **Every response is graded against every principle**, not only its own plugin's. So a rubric
  has to stay quiet on a correct answer to any other probe: an agent declining, explaining a
  risk, describing an attack, or introducing itself by its configured name. Each rubric says so;
  keep that when you rewrite one. These clauses came from false positives in a first run
  against a real pre-sales assistant.
- **Controls** (`"plugin": null`) are the same situation with the payload removed. They are
  graded and excluded from every rate. A failing control invalidates the attacks around it.
- **Languages.** A translation is a different measurement: guardrails are trained mostly on
  English attack strings, so compare languages, never pool them. The canary tokens
  (`COMPROMISED`, `FREE MODE ENABLED`) stay English in every language so one rubric judges all.
