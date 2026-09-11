# The command line

`redteam`, parsed with the standard library and rendered with rich. The API is its only door to
the platform; docker compose is its only door to the local stack. It ships as one file per platform
on each release (`redteam-<os>-<arch>.pyz`, Python 3.12 on the target) and as `uv run redteam` in a
checkout.

```
redteam init [--api-url] [--receiver-url]
redteam local up [--build] | down | status | logs [service] [-f]
redteam catalogue validate <dir> | publish <name> <dir> | list
redteam prior publish <name> <file>
redteam run validate <spec> | start <spec> [--follow] [--deadline S] | status <id> | result <id> | list | resume <id>
redteam receiver export <run_id>
redteam --json <any command>
```

## The workspace

`.redteam/` beside the operator's work, found from any directory below it: `config.json` (the API
and the receiver), `.env` (the local stack's credentials, `0600`, created from a template and never
overwritten), `catalogues/<name>/published.json`, `runs/<id>/{accepted,status,manifest,delivery}.json`.
The store is the platform's record; this is the operator's notebook.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | done |
| 1 | the API refused (its words are the output), the run failed, or a file is malformed |
| 2 | no workspace here or above; `redteam init` |
| 3 | nothing answered: the API is down, or docker is missing |
| 4 | the run is stalled; `redteam run resume <id>` |
| 5 | `--follow` reached its deadline |

## Modules

- `main.py`: the argparse tree and the rich rendering; `main(argv, out=, err=)` takes its consoles.
- `api.py`: the HTTP client, `ApiError`/`Unreachable`, the receiver's reader.
- `bundle.py`: a bundle directory as the API's request body, with the contracts package alone.
- `workspace.py`: the `.redteam/` directory.
- `local.py`: docker compose, with the compose file from the checkout or from inside the wheel.
