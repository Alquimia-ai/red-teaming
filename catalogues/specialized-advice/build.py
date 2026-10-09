"""Build a publishable schema-v2 document from the per-risk YAML sources.

The YAMLs under risks/ are the source. This assembles the ones you choose into one document and
never edits the JSON by hand, so source and output cannot drift.

  python build.py                              every risk, weights split evenly -> <family>.json
  python build.py --risks a,b,c                only those risks, weights split evenly among them
  python build.py --weights a=0.5,b=0.3,c=0.2  chosen risks, severities normalised to sum 1
  python build.py --risks a,b --out bpd.json   write somewhere other than the default

A risk is the stem of a file under risks/ (its plugin id). `--list` prints them.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

try:
    import yaml
except ImportError:
    sys.exit("needs pyyaml: run with `uv run python build.py`")

HERE = pathlib.Path(__file__).parent
RISKS = HERE / "risks"
FAMILY = HERE.name
DEFAULT_OUT = HERE / f"{FAMILY}.json"
DEFAULTS = {"entity_kind": "assistant", "transform": "keep_real", "doc": 0, "requires_brain": False}


def available() -> list[str]:
    return sorted(p.stem for p in RISKS.glob("*.yaml"))


def parse_weights(text: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for pair in text.split(","):
        name, _, value = pair.partition("=")
        if not value:
            sys.exit(f"--weights wants name=number pairs, got {pair!r}")
        out[name.strip()] = float(value)
    return out


def strategy(s: dict, plugin: str | None) -> dict:
    it = dict(s["interaction"])
    if it["mode"] == "adaptive_multi_turn":
        it.setdefault("attacker", "crescendo")
    return {
        "id": s["id"],
        "name": s["name"],
        "description": s["description"],
        "plugin": plugin,
        **DEFAULTS,
        "interaction": it,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--risks", help="comma-separated risk ids to include; default every risk")
    ap.add_argument(
        "--weights", help="comma-separated id=severity; sets the risk set and its weights"
    )
    ap.add_argument("--name", default=FAMILY, help="catalogue name in the document")
    ap.add_argument("--out", type=pathlib.Path, help=f"output path; default {DEFAULT_OUT.name}")
    ap.add_argument("--list", action="store_true", help="print the available risks and exit")
    args = ap.parse_args()

    have = available()
    if args.list:
        print("\n".join(have))
        return

    if args.weights:
        weights = parse_weights(args.weights)
        chosen = list(weights)
    elif args.risks:
        chosen = [r.strip() for r in args.risks.split(",")]
        weights = None
    else:
        chosen = have
        weights = None

    unknown = [r for r in chosen if r not in have]
    if unknown:
        sys.exit(f"unknown risks: {unknown}. available: {have}")

    if weights is None:
        even = round(1 / len(chosen), 6)
        weights = {r: even for r in chosen}
        weights[chosen[-1]] = round(1 - even * (len(chosen) - 1), 6)
    else:
        total = sum(weights.values())
        weights = {r: round(w / total, 6) for r, w in weights.items()}
        weights[chosen[-1]] = round(1 - sum(list(weights.values())[:-1]), 6)

    principles, plugins, strategies = [], [], []
    for pid in chosen:
        d = yaml.safe_load((RISKS / f"{pid}.yaml").read_text(encoding="utf-8"))
        pr, pl = d["principle"], d["plugin"]
        principles.append({"id": pr["id"], "weight": weights[pid], "rubric": pr["rubric"]})
        plugins.append(
            {
                "id": pl["id"],
                "name": pl["name"],
                "description": pl["description"],
                "principle": pr["id"],
            }
        )
        strategies += [strategy(s, pid) for s in d["attacks"]]
        strategies += [strategy(s, None) for s in d["controls"]]

    doc = {
        "schema_version": 2,
        "name": args.name,
        "contract": {
            "version": "v1",
            "verdict": {"positive": ["YES", " YES", "Yes"], "negative": ["NO", " NO", "No"]},
            "principles": principles,
        },
        "plugins": plugins,
        "strategies": strategies,
    }
    out = args.out or DEFAULT_OUT
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    attacks = sum(s["plugin"] is not None for s in strategies)
    print(
        f"{out.name}: {len(plugins)} risks, {attacks} attacks, {len(strategies) - attacks} controls"
    )
    print("weights: " + ", ".join(f"{r}={weights[r]}" for r in chosen))


if __name__ == "__main__":
    main()
