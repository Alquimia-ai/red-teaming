# The command line

`redteam`, parsed with the standard library and rendered with rich. The API is its only door to
the platform; docker compose is its only door to the local stack. It ships as one file per platform
on each release (`redteam-<os>-<arch>.pyz`, Python 3.12 on the target) and as `uv run redteam` in a
checkout.

```
redteam init [--api-url] [--receiver-url]
redteam local up [--build] | down | status | logs [service] [-f]
redteam catalogue validate <file> | publish <file> | list
redteam prior publish <name> <file>
redteam run validate <spec> | start <spec> [--follow] [--deadline S] | status <id> | result <id> | list | resume <id>
redteam receiver export <run_id>
redteam update [--check] [--tag cli-v0.2.0] [--force]
redteam --version
redteam --json <any command>
```

## Installing it, and keeping it

```bash
curl -fsSL https://raw.githubusercontent.com/Alquimia-ai/red-teaming/main/install.sh | sh
redteam --version            # redteam 0.1.0
redteam update --check       # what is released, and whether it is newer than this
redteam update               # take it
```

`install.sh` resolves the newest `cli-v*` release -- the command line's own tag, never the
repository's newest release -- downloads the asset `uname` resolves to, checks it against the
digest the release published, and installs it as one executable file in `$HOME/.local/bin`
(`--dir` elsewhere, `--version cli-v0.2.0` to pin, `--from <file.pyz>` for a local build).

`redteam update` is the same walk from inside the command line: it reads the releases API, compares
versions by number, downloads this platform's asset, verifies its digest and renames the new file
over the file it is running from. Interrupted, it leaves the command line it had. It refuses to
guess when this is not a single file -- a checkout or a wheel is updated by whatever installed it --
and says what to run instead. A private repository needs `REDTEAM_GITHUB_TOKEN` (or `GITHUB_TOKEN`)
in the environment: it is the only thing in the command line that reads a credential off it, and it
authorises nothing but the releases request.

`docs/release.md` is the whole lifecycle: built on every pull request, every platform proved on
`develop`, published by release-please on `main`.

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

`redteam update` uses the same three: 0 done or nothing newer, 1 the download was not what the
release published or the file cannot be replaced, 3 the releases API did not answer.

## Modules

- `main.py`: the argparse tree and the rich rendering; `main(argv, out=, err=)` takes its consoles.
- `api.py`: the HTTP client, `ApiError`/`Unreachable`, the receiver's reader.
- `bundle.py`: one YAML or JSON catalogue document as the API request body.
- `workspace.py`: the `.redteam/` directory.
- `local.py`: docker compose, with the compose file from the checkout or from inside the wheel.
- `release.py`: where the releases are, which asset this platform wants, and how one file replaces
  itself. The only place the command line names the repository it came from.
