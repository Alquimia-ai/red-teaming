# Deferred risks

Two OWASP risks that are **written but not shipped**. The catalogues in this folder are
complete and valid; they are held back on an evidence argument, not on effort.

Nothing here is loaded by the assembler. Moving one file up into `../security/` is all it
takes to activate it, once the gap below is closed.

## The reason both are here

Everything RoastMe observes is **the agent's own answer**. For most risks that is enough,
because the answer *is* the failure: an injected order obeyed, a system prompt disclosed, an
exfiltration URL built. The text in front of the judge is the thing that went wrong.

These two are different. The failure does not happen in the text. It happens in a **store**
the probe cannot see:

| Risk | Where the failure actually lands | What the answer gives us |
|---|---|---|
| Memory Poisoning | the memory the agent carries into later sessions | the agent *saying* it noted something |
| Denial of Wallet | tokens, tool calls, the bill | the agent *saying* it will keep going |

So the measurement is the agent's self-report about its own state, and a self-report is a
claim, not evidence. An agent can answer "I cannot retain instructions between
conversations" and retain them. It can answer "that has no end, how many do you need" and
still have been walked into a runaway loop by a different phrasing. Neither direction of that
result is anchored to anything observable.

This repo's standard is evidence with provenance, reproducible against a snapshot. A number
produced by asking the agent to describe its own memory does not meet it, and a plugin that
reports a rate nobody can verify is worse than no plugin: in a report, an unverifiable zero
is indistinguishable from a verified one.

Both therefore need the same missing thing, in two different shapes: **a read of the backend**.
Until the state that was affected can be observed on the side that holds it, these two produce
opinions, and the rest of this catalogue produces evidence.

## What each one is, and what would unblock it

### Memory Poisoning (`memory_poisoning.yaml`)

**The risk.** An attacker plants an instruction or a false fact that the agent retains, so it
governs later exchanges, or other users. Two movements: plant now, collect later.

**What the catalogue measures.** The first movement only: whether the agent accepts a rule it
was asked to hold "from now on", accepts a user assertion as stored policy, or acts on a
planted rule later in the same exchange. Six attacks, three controls.

**Why that is not enough.** Acceptance is inferred from the agent saying it accepted. There is
no way to read back what was actually stored, to compare the system prompt before and after,
or to see whether anything reached whatever the agent consumes on the next run.

**What would unblock it.** Two things, and **both**, not either:

1. **A second session** against the same store. Plant in session A, probe in session B. This
   is what turns "it said it noted the rule" into "the rule survived the session boundary".
2. **A read of the backend.** What the store actually holds after the attack: the record, the
   retained instruction, whatever the agent will consume on its next run.

The second session alone is not enough, and that is the part worth being careful about. A
different answer in session B is consistent with the rule having been stored, but it is also
consistent with sampling variance, a different retrieval, or the agent simply phrasing itself
differently. Behaviour is downstream of the store and does not identify it. Without reading
the store, session B upgrades the evidence from "the agent says so" to "the agent behaves
differently", which is better and still not the thing itself.

With both, the failure becomes an artifact that can be pointed at, diffed against the state
before the attack, and reproduced. That is the standard the rest of this catalogue already
meets, which is the whole reason this one is not shipped beside it.

The catalogue needs no change either way: the same six attacks become valid measurements the
day the harness can plant, cross a session boundary, and read back.

### Denial of Wallet (`denial_of_wallet.yaml`)

**The risk.** Unbounded agent loops burning API and compute cost: endless repetition, uncapped
output, retries with no ceiling, procedures that refer back to themselves.

**What the catalogue measures.** Whether the agent *agrees* to unbounded work. Six attacks,
three controls.

**Why that is not enough.** The risk is denominated in cost, and cost is not in the text. An
agreement is not a bill, and a refusal is not a budget. The judge is being asked to rate
something it cannot see.

**What would unblock it.** A cost meter read **from the backend**, per probe: tokens consumed,
tool calls fired, chain depth reached, wall time. Not the adapter's own estimate of what it
sent, and certainly not the agent's account of itself — the figure has to come from the side
that actually spends, which is the runtime or the provider's usage reporting.

That distinction is the whole point. The agent answering "I will keep going forever" costs
almost nothing, and an agent answering "that has no end, how many do you need" may already
have burned a fortune on a different phrasing. Agreement and cost are not correlated, so a
grader reading text is rating the wrong variable.

With a backend meter the plugin stops being a judgement and becomes arithmetic: cost per
probe, against a threshold the platform owner sets. The rubric largely disappears, and the
same six attacks become the inputs to a measurement rather than the measurement itself.

Worth saying plainly: the real control for this risk is not a test at all. It is enforcement
on the platform — per-session token budgets, tool-call rate limits, chain-depth caps, circuit
breakers. The measurement tells you whether those hold; it does not substitute for them.

## One thing to fix before activating either

Both files are still **Spanish only**. The shipped catalogues in `../security/` carry
`description`, `phrasing_hint` and `turns` as per-language dicts (`es`, `en`); these two were
frozen before that change and carry plain strings.

Whoever activates one has to convert it, or the assembler will hand gaussia a dict where it
expects a string. Deliberately not done in advance: the attacks may well need rewriting once
there is a real observation channel, and translating text that is about to change is wasted
work.

## Where this leaves the coverage

Both risks stay on the OWASP map with an explicit status, rather than silently disappearing.
A report over this catalogue must say that these two were **not measured** — never that they
were measured and came out clean.
