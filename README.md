# red-teaming

Red teaming for Alquimia assistants.

Generate adversarial probes anchored in a knowledge base, conduct governed multi-turn
conversations against a live assistant, keep every conversation as immutable evidence, and
deliver the attack dataset, the weakness profile, the exploitation report and a manifest with
honest coverage: what was planned, what closed, what failed.

## Repository

```
apps/            api · runner · cli
packages/        redteam_<name> libraries
deploy/          compose · charts · catalog · cloud · appliance
docs/            adr · architecture · components · deploy
tests/guards/    architectural guards
```

The repository is being built in phases; see [`CLAUDE.md`](CLAUDE.md) for the current state, the
invariants and the vocabulary, and [`docs/adr/`](docs/adr/) for the decisions.

## Develop

```bash
uv sync --all-packages
uv run pytest -q -m "not live and not docker and not k8s"
uv run ruff check . && uv run mypy packages apps tests
```

Contribution rules -- branches, commit scopes, releases -- are in
[`CONTRIBUTING.md`](CONTRIBUTING.md).
