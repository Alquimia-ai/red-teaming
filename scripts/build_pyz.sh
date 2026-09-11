#!/usr/bin/env bash
# Build the `redteam` command line as one file: a zipapp that runs with the platform's Python 3.12.
#
# Two steps, and the first is why this is a script rather than one `shiv` line: the command line
# depends on a workspace member (`red-teaming-contracts`) that no index serves, so both are built
# as wheels first and shiv resolves the member from that directory and everything else from PyPI.
#
#   scripts/build_pyz.sh [out-dir]     -> <out-dir>/redteam-<os>-<arch>.pyz
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$HERE/dist}"
WHEELS="$OUT/wheels"
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
PYZ="$OUT/redteam-$OS-$ARCH.pyz"

mkdir -p "$WHEELS"
cd "$HERE"
uv build --package red-teaming-contracts --wheel --out-dir "$WHEELS" >/dev/null
uv build --package red-teaming-cli --wheel --out-dir "$WHEELS" >/dev/null

# A zipapp built for one Python runs on that Python: the interpreter line asks the platform for
# the same minor version the wheels were resolved against.
uvx --python 3.12 --from shiv shiv \
  --compressed \
  --reproducible \
  --python "/usr/bin/env python3.12" \
  --console-script redteam \
  --output-file "$PYZ" \
  --find-links "$WHEELS" \
  red-teaming-cli

echo "$PYZ"
