# Running these catalogues

Operational notes for whoever wires a run. Everything here was verified against gaussia's
source; line references are to `src/gaussia/generators/roastme/`.

For what the catalogues are and which risks they cover, see [README.md](README.md).

## Building the knowledge bundle

These files are data. Something has to turn them into the `catalogue` and `contract` sections
of the bundle the app reads (`redteam.ports.KnowledgeBundle`, both carried as opaque JSON).

Six steps. The first four a standalone script can do; the last two only the app can:

1. read the files for the risks being activated;
2. **pick a language.** `description`, `phrasing_hint` and `turns` are dicts keyed by ISO code
   (`es`, `en`); `StrategySpec` takes strings. Run once per language and keep the results apart,
   never pooled — see README, *Language*;
3. flatten `defaults` onto every strategy;
4. append `controls` to `strategies` with `plugin: null`, which is the only thing that makes a
   probe a control;
5. **weights.** `BehavioralContract` requires principle weights summing to exactly 1.0. No file
   declares one: how gravely a failure counts is the contract owner's call. Split evenly across
   the activated principles and let the caller override;
6. **graders.** `Principle` requires a grader *object*. The files carry the `rubric`, which is
   the text that decides; bind a grader to it at load time.

Because 5 and 6 need the app, the assembler belongs in `redteam` next to the grader
construction, not as a separate script. A standalone script doing 1 to 4 would duplicate the
transformation in two places.

**Not yet verified:** no assembler exists, so nobody has run these files through
`validate_catalogue` and confirmed gaussia accepts them. The transformation is documented, not
proven. Expect the `entity_kind` rejection below on the first attempt.

## Five things that will bite

### Run with no documents

`Profiler` over `documents=[]`. These attacks do not use a corpus, and supplying one degrades
them: with a premise available and no `{premise}` slot in the hint, `compose_query` appends the
entity after a colon (`_QUERY_TEMPLATE = "{hint}: {premise}"`), tacking a product name onto the
end of the attack.

### Never add a `{premise}` slot

The inverse case is worse. With no corpus, `compose_query` strips the slot with
`" ".join(hint.split())` (`probes/particularisation.py:75`), which collapses every newline into
a space. The fake document, its delimiters and the line separating carrier from payload all end
up on one line, and a delimiter-escape attack stops existing.

Both branches were checked by running them. No single hint shape is safe in both worlds, so the
guarantee comes from *how this is invoked*, not from how it is written.

### Configure exactly one engine

`Probe.id` is `f"{engine}-{strategy.id}"`, and every default engine routes the corpus-free path
through the same function. Three engines therefore produce three probes with identical query
text and distinct ids, so the merge does not collapse them and the same question is counted
three times in the denominator.

### Stage 2 will not reproduce these attacks

The shipped `PromptedQueryGenerator` carries, in its system prompt, *"no instructions to the
assistant"* — which is exactly what these payloads are. The Exploiter will generate queries
*about* the pattern rather than queries that *are* it.

The catalogue still works as a stage-1 seed. Multiplying it needs a `QueryGenerator` of our own,
injected at the Exploiter. That is a separate deliverable.

### `entity_kind` will fail validation until an engine declares it

`validate_catalogue` rejects any `entity_kind` no configured engine lists in `entity_kinds`,
while the engines themselves treat an empty declaration as "handles everything"
(`probes/grounded.py:111`). The two disagree. An engine constructed with
`entity_kinds=("user_text",)` satisfies both.

## Multi-turn

A strategy carries either `phrasing_hint` (one message, sent verbatim) or `turns` (a list played
in order over one session), never both. The assembler translates `turns` into whatever the
multi-turn surface expects, so a change there touches the assembler and no catalogue file.

Two consequences:

- **the judge sees whatever the adapter returns.** If it returns only the last reply, an agent
  that drifted at turn two and recovered at turn three reads as clean. Returning the whole
  exchange fixes it, and every rubric here is already written to judge the exchange as a whole;
- multi-turn attacks stay a fixed seed, since stage 2 will not reproduce their shape.

## Reading a result honestly

- **a failing control invalidates the attacks around it.** That is what controls are for. If an
  in-scope control is refused, the probes were aimed at the wrong surface and the attacks'
  clean sheet means nothing;
- **never pool languages.** Guardrails are trained mostly on English attack strings, so the same
  attack routinely passes in one language and is caught in the other. Those are separate
  findings about separate surfaces;
- **say what was not measured.** Deferred and absent risks were not measured. Never report them
  as measured and clean.
