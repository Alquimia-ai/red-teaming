#!/bin/sh
# Install the `redteam` command line from this repository's releases.
#
#   curl -fsSL https://raw.githubusercontent.com/Alquimia-ai/red-teaming/main/install.sh | sh
#   curl -fsSL .../install.sh | sh -s -- --version cli-v0.2.0 --dir /usr/local/bin
#   sh install.sh --from dist/redteam-linux-x86_64.pyz    # a zipapp built from this checkout
#   sh install.sh --print-asset                           # what this machine would download
#
# The command line is released on `main` by release-please under its own tag -- `cli-v<version>`,
# never the repository's newest release, which usually belongs to an image -- and every such release
# carries one zipapp per platform with its `.sha256` beside it. This script resolves the newest of
# those tags, downloads the asset this platform's name resolves to, checks it against its published
# digest and installs it as one executable file. After that, `redteam update` does the same thing
# from inside the command line itself.
#
# This script is read from `main` over curl, so it carries no version of its own: what it installs
# is decided by the releases it finds, and `--version` pins one. POSIX sh on purpose -- it is piped
# into whatever `sh` is on the machine.
#
# Environment: REDTEAM_INSTALL_DIR, REDTEAM_VERSION, REDTEAM_GITHUB_TOKEN or GITHUB_TOKEN (a private
# repository's releases), REDTEAM_OS and REDTEAM_ARCH (name a platform other than this one).
set -eu

OWNER="Alquimia-ai"
REPOSITORY="red-teaming"
TAG_PREFIX="cli-v"
GITHUB_API="https://api.github.com"
GITHUB_DOWNLOAD="https://github.com"
PYTHON="python3.12"
COMMAND="redteam"

DIR="${REDTEAM_INSTALL_DIR:-$HOME/.local/bin}"
TAG="${REDTEAM_VERSION:-}"
TOKEN="${REDTEAM_GITHUB_TOKEN:-${GITHUB_TOKEN:-}}"
FROM=""
PRINT_ASSET=""
CHECK_PYTHON=1

say() { printf '%s\n' "$*" >&2; }
die() { printf 'redteam: %s\n' "$*" >&2; exit 1; }

usage() {
  cat >&2 <<'USAGE'
install.sh [options]

  --version <tag>   a release to install instead of the newest (cli-v0.2.0, or 0.2.0)
  --dir <path>      where to install it (default: $HOME/.local/bin)
  --from <file>     install a zipapp from this machine instead of a release
  --print-asset     print the asset this platform resolves to, and stop
  --no-python-check install even when python3.12 is not on the PATH
  --help
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --version) TAG="${2:?--version needs a tag}"; shift 2 ;;
    --dir) DIR="${2:?--dir needs a path}"; shift 2 ;;
    --from) FROM="${2:?--from needs a path}"; shift 2 ;;
    --print-asset) PRINT_ASSET=1; shift ;;
    --no-python-check) CHECK_PYTHON=0; shift ;;
    --help|-h) usage; exit 0 ;;
    *) usage; die "unknown argument: $1" ;;
  esac
done

# ---- which asset this platform wants ------------------------------------------------------------
# The names are `uname` as the machines that build the assets answer it; every other spelling of the
# same platform is folded onto one of them. `redteam_cli.release.asset_name` answers the same, and a
# guard holds the two together: an installer that named a different file would install one command
# line and update to another.

os="$(printf '%s' "${REDTEAM_OS:-$(uname -s)}" | tr '[:upper:]' '[:lower:]')"
arch="$(printf '%s' "${REDTEAM_ARCH:-$(uname -m)}" | tr '[:upper:]' '[:lower:]')"

case "$os" in
  linux)
    case "$arch" in
      x86_64|amd64|x64) arch="x86_64" ;;
      aarch64|arm64|armv8l) arch="aarch64" ;;
      *) arch="" ;;
    esac ;;
  darwin)
    case "$arch" in
      arm64|aarch64) arch="arm64" ;;
      x86_64|amd64) arch="x86_64" ;;
      *) arch="" ;;
    esac ;;
  *) os="" ;;
esac

if [ -z "$os" ] || [ -z "$arch" ]; then die \
  "no release asset for ${REDTEAM_OS:-$(uname -s)}/${REDTEAM_ARCH:-$(uname -m)}; the command line is released for linux and macOS on x86_64 and arm, and runs from a checkout with \`uv run redteam\` anywhere"; fi

ASSET="$COMMAND-$os-$arch.pyz"

if [ -n "$PRINT_ASSET" ]; then
  printf '%s\n' "$ASSET"
  exit 0
fi

# ---- what it takes to run it --------------------------------------------------------------------
# The zipapp's own first line asks the platform for python3.12: the wheels inside it were resolved
# against that version. Saying so now is better than an exec failure from a file that looks installed.

if [ "$CHECK_PYTHON" -eq 1 ] && ! command -v "$PYTHON" >/dev/null 2>&1; then
  die "$PYTHON is not on the PATH, and the command line runs on it (\`brew install python@3.12\`, \`apt install python3.12\`, or https://github.com/astral-sh/uv). Pass --no-python-check to install anyway"
fi

# ---- fetching ------------------------------------------------------------------------------------

if command -v curl >/dev/null 2>&1; then
  DOWNLOADER="curl"
elif command -v wget >/dev/null 2>&1; then
  DOWNLOADER="wget"
else
  die "neither curl nor wget is on the PATH"
fi

# get <url> <accept> [output]; with no output, the body goes to stdout.
get() {
  _url="$1"; _accept="$2"; _out="${3:-}"
  if [ "$DOWNLOADER" = "curl" ]; then
    set -- -fsSL -H "Accept: $_accept"
    if [ -n "$TOKEN" ]; then set -- "$@" -H "Authorization: Bearer $TOKEN"; fi
    if [ -n "$_out" ]; then set -- "$@" -o "$_out"; fi
    curl "$@" "$_url"
  else
    set -- -q -O "${_out:--}" --header="Accept: $_accept"
    if [ -n "$TOKEN" ]; then set -- "$@" --header="Authorization: Bearer $TOKEN"; fi
    wget "$@" "$_url"
  fi
}

api() { get "$1" "application/vnd.github+json"; }

# ---- the release -----------------------------------------------------------------------------

newest_tag() {
  # The listing is newest first, and every component releases under its own tag; of the ones that
  # are the command line's, take the highest version rather than trusting the order.
  api "$GITHUB_API/repos/$OWNER/$REPOSITORY/releases?per_page=100" \
    | tr ',' '\n' \
    | sed -n "s/.*\"tag_name\"[[:space:]]*:[[:space:]]*\"$TAG_PREFIX\([^\"]*\)\".*/\1/p" \
    | sort -t. -k1,1n -k2,2n -k3,3n \
    | tail -n 1
}

asset_api_url() {
  # A private repository's assets are downloaded from the API, by id, not from the browser URL.
  # Each asset is one object in the release's JSON: split on `{`, keep the one with this name.
  api "$GITHUB_API/repos/$OWNER/$REPOSITORY/releases/tags/$1" \
    | tr '{' '\n' \
    | grep "\"name\"[[:space:]]*:[[:space:]]*\"$2\"" \
    | sed -n 's|.*"url"[[:space:]]*:[[:space:]]*"\([^"]*releases/assets/[0-9]*\)".*|\1|p' \
    | head -n 1
}

# ---- what to install -----------------------------------------------------------------------------

TMP="$(mktemp -d "${TMPDIR:-/tmp}/redteam-install.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT INT TERM
payload="$TMP/$ASSET"

if [ -n "$FROM" ]; then
  [ -f "$FROM" ] || die "$FROM is not a file"
  cp "$FROM" "$payload"
  TAG="local"
  say "==> installing $FROM"
else
  case "$TAG" in
    "") version="$(newest_tag)"; [ -n "$version" ] || die \
          "no ${TAG_PREFIX}* release in $OWNER/$REPOSITORY; a private repository needs REDTEAM_GITHUB_TOKEN in the environment"
        TAG="$TAG_PREFIX$version" ;;
    "$TAG_PREFIX"*) ;;
    v*) TAG="$TAG_PREFIX${TAG#v}" ;;
    *) TAG="$TAG_PREFIX$TAG" ;;
  esac

  say "==> $TAG: downloading $ASSET"
  if [ -n "$TOKEN" ]; then
    url="$(asset_api_url "$TAG" "$ASSET")"
    [ -n "$url" ] || die "$TAG carries no $ASSET"
    checksum_url="$(asset_api_url "$TAG" "$ASSET.sha256")"
  else
    url="$GITHUB_DOWNLOAD/$OWNER/$REPOSITORY/releases/download/$TAG/$ASSET"
    checksum_url="$GITHUB_DOWNLOAD/$OWNER/$REPOSITORY/releases/download/$TAG/$ASSET.sha256"
  fi
  get "$url" "application/octet-stream" "$payload" \
    || die "could not download $ASSET from $TAG; is the release published, and does it carry this platform?"

  # ---- the digest the release published -------------------------------------------------------
  if [ -n "$checksum_url" ] && get "$checksum_url" "application/octet-stream" "$TMP/sha256" 2>/dev/null; then
    expected="$(cut -d' ' -f1 < "$TMP/sha256" | tr -d '\r\n')"
    if command -v sha256sum >/dev/null 2>&1; then
      actual="$(sha256sum "$payload" | cut -d' ' -f1)"
    elif command -v shasum >/dev/null 2>&1; then
      actual="$(shasum -a 256 "$payload" | cut -d' ' -f1)"
    else
      actual=""
      say "    no sha256sum or shasum on the PATH; the download is not checked"
    fi
    if [ -n "$actual" ] && [ "$expected" != "$actual" ]; then
      die "$ASSET hashes to $actual, $TAG publishes $expected; nothing was installed"
    fi
    if [ -n "$actual" ]; then say "    sha256 $actual"; fi
  else
    say "    $TAG publishes no checksum for $ASSET; the download is not checked"
  fi
fi

# ---- installing it -------------------------------------------------------------------------------
# Into the destination directory first, then renamed over whatever is there: on one filesystem the
# rename is atomic, so a `redteam` that is being replaced is never a half-written file.

mkdir -p "$DIR" || die "$DIR could not be created"
target="$DIR/$COMMAND"
incoming="$DIR/.$COMMAND.incoming.$$"
cp "$payload" "$incoming" || die "$DIR is not writable; pass --dir, or run this with the rights to write there"
chmod 755 "$incoming"
mv -f "$incoming" "$target"

installed="$("$target" --version 2>/dev/null || true)"
[ -n "$installed" ] || die "$target was installed but does not run; is $PYTHON on the PATH?"

say ""
say "==> $installed  ($TAG)"
say "    $target"
case ":$PATH:" in
  *":$DIR:"*) say "    try: $COMMAND --help" ;;
  *) say "    $DIR is not on your PATH -- add it:"
     say "      export PATH=\"$DIR:\$PATH\"" ;;
esac
say "    update it later with: $COMMAND update"
