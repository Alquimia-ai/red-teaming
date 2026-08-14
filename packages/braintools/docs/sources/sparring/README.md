# Sparring sources

Interactive sparring / red-teaming findings, captured as **committed source documents**
so they become reproducible, git-shared brain knowledge (subject `sparring`).

This is the seed path: collaboration happens on these files via git, and everyone
rebuilds the brain with `braintools seed`. (Operational knowledge that is non-
deterministic or model-extracted belongs in the registry path instead — see
`../../../../README.md` and the repo `CLAUDE.md`.)

## Convention

- **One file per session/finding.**
- **Filename:** `YYYY-MM-DD-<author>-<slug>.md` (deterministic, sortable).
- **Structure:** headings with content (the `structure` proposer extracts from those),
  and metadata baked into the body so who/when survives a rebuild.

## Create one

```bash
uv run braintools spar "prompt injection via tool args" --author leonardo \
    --target alquimia-core --context "probing the support agent"
# fill in the file it prints, then:
git add docs/sources/sparring/ && git commit -m "spar: ..." && git push
uv run braintools seed        # ingests it (subject: sparring); collaborators do the same after git pull
```

This `README.md` is ignored by `seed` (it documents the convention; it is not knowledge).
