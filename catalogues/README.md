# Security catalogues

Default RoastMe catalogues for the agent-security risks of the
[OWASP AI Agent Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html).

They are **data, not code**. Nothing here imports gaussia. Gaussia ships no contract and no
catalogue on purpose — a contract is what counts as failure, so a shipped one would be the
library deciding that for everyone. These are Alquimia's defaults for Alquimia's agents: a
consumer activates the risks it cares about and ignores the rest.

Seven files in `security/`, **49 attacks and 21 controls**, each in Spanish and English.

- **Using these in a run?** → [RUNNING.md](RUNNING.md)
- **Wondering about the three we held back?** → [deferred/README.md](deferred/README.md)

## What we cover

| OWASP risk | File |
|---|---|
| Prompt Injection (Direct & Indirect) | `security/prompt_injection.yaml` |
| Goal Hijacking | `security/goal_hijacking.yaml` |
| Sensitive Data Exposure | `security/sensitive_data_exposure.yaml` **+** `security/third_party_data.yaml` |
| Data Exfiltration | `security/data_exfiltration.yaml` |
| Tool Abuse & Privilege Escalation | `security/tool_abuse.yaml` |
| Excessive Autonomy **+** High-Impact Action Abuse | `security/high_impact_actions.yaml` |

Two rows do not map one-to-one, in opposite directions.

**Sensitive Data Exposure is two files.** OWASP puts "configuration leaked" and "somebody
else's data leaked" under one heading, but they are two obligations with different evidence and
different fixes, and an agent can hold one while failing the other. One rubric covering both
gives a rate nobody can read, because you cannot tell which half broke.

**Excessive Autonomy and High-Impact Action Abuse are one file.** They differ by intent, which
a black-box probe cannot see: both produce the same observable, an agent committing to something
irreversible with no confirmation. Two plugins would share one rubric and charge the weight
budget twice for one measurement.

## What we held back, and why

Written and valid, sitting in `deferred/`. Each fails for a reason no rewording fixes.

| Risk | Why |
|---|---|
| Memory Poisoning | fails in the memory carried to the next session. All the answer gives is the agent's word about its own state. Needs a second session **and** a read of the backend |
| Denial of Wallet | fails in the bill. Needs a cost meter on the side that spends; agreement and cost are not correlated |
| Decision and Approval Manipulation | an assessment can only be shown to have *moved* against a baseline, so it needs turn 1 to elicit the agent's position before turn 2 pushes. No single-turn version measures anything |

## What we do not cover at all

Cascading Failures, AI Console Malicious Configuration, Supply Chain Attacks.

These are architecture and process controls: multi-agent topology, console access, dependency
provenance. A plugin for them would report zero on every run, and not because the agent is safe.
**A zero that means "not tested" is indistinguishable in a report from a zero that means "held".**

> Any report over this catalogue must say the deferred and absent risks were **not measured** —
> never that they were measured and came out clean.

## Which files to review before using them

All seven run as-is against any agent. Three measure more when reviewed against the agent first,
and one has a precondition.

| File | Review first? | Why |
|---|---|---|
| `prompt_injection` | no | an obeyed order is the same failure in any domain |
| `sensitive_data_exposure` | no | a disclosed system prompt is the same failure in any domain |
| `third_party_data` | no | somebody else's data is somebody else's in any domain |
| `data_exfiltration` | read with the channel | the markdown beacon only fires where markdown renders |
| `goal_hijacking` | **recommended** | the rubric is what decides "out of scope" |
| `tool_abuse` | **recommended** | a refusal may mean "cannot", not "will not" |
| `high_impact_actions` | **required** | same, plus it assumes the agent can execute actions |

### Reviewing means pushing in two directions

- **attacks must be things the agent should refuse.** If an attack asks for something the agent
  cannot do anyway, the refusal is free and the probe measured nothing;
- **controls must be things the agent should do.** If a control asks for something outside its
  scope, the control fails — and a failing control is what tells you the run was aimed at the
  wrong surface.

So sharpening a file means pushing the attacks further outside the agent's scope and pulling the
controls further inside it. Both are edits to `phrasing_hint`. No structural change.

### One precondition, owned by the consumer

`high_impact_actions.yaml` assumes the agent **can execute actions**. Against a read-only agent
every attack is declined because it *cannot* act, and the zero means "nothing to attack" rather
than "held". No probe separates those from outside, and asking the agent is a self-report —
agents routinely read "execute an action" as "answer a question". So it is declared, not
detected.

## How a file is shaped

```yaml
id: prompt_injection
owasp: "Prompt Injection (Direct & Indirect)"
principle:                  # the RULE that can be broken
  id: no_instruction_from_data
  rubric: |                 # the only text the judge reads
defaults:                   # entity_kind, transform, doc — schema-required, inert here
strategies:                 # the attacks. Each becomes one probe
controls:                   # same shape, no plugin. Excluded from every violation rate
```

**One risk, one rule, one plugin.** Strategies differ in *how* an attack is smuggled in, never
in *what rule it breaks*. A different rubric means a different rule, so it is a different plugin.
That is what keeps a violation rate readable: every probe under a plugin was judged against one
definition of failure.

**The rubric is the whole measurement** — the grader is a model and the rubric is the only text
it reads. Every one here has three parts: what is expected, what counts as a violation, and what
explicitly does **not**. Without the third, an agent that correctly *describes* an attack gets
scored as having fallen for it.

**Rubrics are meant to be changed.** If one does not match what your agent is held to, rewrite
it — that is the normal way to use this catalogue. Keep the third part, and keep it to one rule:
a rubric covering two obligations makes its rate unreadable, because you can no longer tell
which one broke.

**Controls are not optional.** A control is the same situation with the payload removed; without
it you cannot tell "vulnerable" from "broken in general" or "the rubric charges too much". Two
kinds appear here, and the second matters more than it looks:

- the **clean** control: the same carrier, no payload;
- the **quoted** control: the payload is there, but the user asks the agent to *describe* it
  rather than run it. Complying means describing it. Without this one, an agent that refuses
  every suspicious text scores zero violations and looks perfect while being useless.

## Language

`description`, `phrasing_hint` and `turns` are dicts keyed by ISO code (`es`, `en`). Everything
else is English, the rubric included.

**A translation is a different measurement.** Guardrails are trained mostly on English attack
strings — *"ignore all previous instructions"* is in every public jailbreak dataset, its Spanish
equivalent far less. The same attack routinely gets caught in one language and sails through in
the other. **Compare per language, never pool.**

**Canary tokens stay English in every language.** `COMPROMISED` and `FREE MODE ENABLED` are
markers, not words: the agent is asked to emit a string, not to understand it. Keeping them
fixed is what lets one English rubric judge every language.

**Adding a language** means adding the key to every dict in the file. A missing key fails loudly
at assembly, which is why this is a dict and not a directory per language — those drift silently,
and you end up comparing nine attacks against seven while the English agent looks safer than it
is. Multi-turn lists must keep the same number of turns across languages.
