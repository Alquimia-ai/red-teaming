"""Where the command line comes from, and how it replaces itself.

The command line is released like the images are, on `main`, by release-please: the `cli-v<version>`
tag carries one zipapp per platform, each with its checksum beside it. `install.sh` at the root of
this repository is what a person curls to get the first one; everything after that is
`redteam update`, which asks the same releases API for the newest `cli-v` tag, downloads the asset
this platform's name resolves to, checks it against its published digest and replaces the running
file in place.

Three things are stated once, here, and held to the installer by a guard
(`tests/guards/test_cli_distribution.py`): where the releases are, which tags belong to the command
line, and how a platform's name becomes an asset's name. An installer that disagreed with the
command line about any of them would install one thing and update to another.
"""

from __future__ import annotations

import hashlib
import io
import os
import platform
import re
import sys
import zipfile
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version
from pathlib import Path
from typing import Any

import httpx

Maker = Callable[..., httpx.Client]
"""How a client is made: the network's, or a test's."""

DISTRIBUTION = "red-teaming-cli"
OWNER = "Alquimia-ai"
REPOSITORY = "red-teaming"
"""Owner and repository apart, never joined into a constant: this is the only place the command
line names where it comes from, and the installer is checked against it."""

TAG_PREFIX = "cli-v"
"""Every component releases under its own tag, so the newest release of this repository is usually
somebody else's. The command line only ever looks at tags that start with this."""

GITHUB_API = "https://api.github.com"
INSTALLER = f"https://raw.githubusercontent.com/{OWNER}/{REPOSITORY}/main/install.sh"

TIMEOUT = 60.0
PAGE = 100
PAGES = 5
"""How far back to look for the newest `cli-v` release. The listing is newest first, so the first
page that holds one holds the newest one; the cap is there so an unexpected answer cannot become an
unbounded walk."""

TOKEN_VARIABLES = ("REDTEAM_GITHUB_TOKEN", "GITHUB_TOKEN")
"""Read only to reach a private repository's releases. Nothing else in the command line reads a
credential off the environment, and this one never leaves the request it authorises."""

SYSTEMS = {"linux": "linux", "darwin": "darwin"}

MACHINES: Mapping[str, Mapping[str, str]] = {
    # What `uname -m` answers on the machine that built each asset, and every spelling of the same
    # architecture a client might report for it.
    "linux": {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "x64": "x86_64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
        "armv8l": "aarch64",
    },
    "darwin": {
        "arm64": "arm64",
        "aarch64": "arm64",
        "x86_64": "x86_64",
        "amd64": "x86_64",
    },
}

ASSETS = frozenset(
    {
        "redteam-linux-x86_64.pyz",
        "redteam-linux-aarch64.pyz",
        "redteam-darwin-arm64.pyz",
        "redteam-darwin-x86_64.pyz",
    }
)
"""Every asset a release carries: one per platform the build matrix runs on. `asset_name` can
answer nothing else, and the guard holds this set to the matrix."""

CHECKSUM_SUFFIX = ".sha256"


class Unsupported(RuntimeError):
    """This platform has no asset, and no release will produce one for it."""


class Unavailable(RuntimeError):
    """The releases API did not answer, or did not answer with a release."""


class NotInstalled(RuntimeError):
    """This command line is not a file that can replace itself."""


class Corrupt(RuntimeError):
    """What was downloaded is not what the release says it is."""


# ---- this build ---------------------------------------------------------------------------------


def version() -> str:
    """The version of the command line running now, as its own distribution records it."""
    try:
        return installed_version(DISTRIBUTION)
    except PackageNotFoundError:  # pragma: no cover - only outside an installed environment
        return "0.0.0"


def asset_name(system: str | None = None, machine: str | None = None) -> str:
    """The release asset for a platform: `redteam-<os>-<arch>.pyz`, as `build_pyz.sh` names it."""
    named = (system or platform.system()).lower()
    hardware = (machine or platform.machine()).lower()
    operating = SYSTEMS.get(named)
    architecture = MACHINES.get(operating or "", {}).get(hardware)
    if operating is None or architecture is None:
        raise Unsupported(
            f"no release asset for {named}/{hardware}; the command line is released for "
            f"{', '.join(sorted(ASSETS))}, and runs from a checkout with `uv run redteam` anywhere"
        )
    return f"redteam-{operating}-{architecture}.pyz"


def zipapp() -> Path | None:
    """The single file this process is running from, when it is one.

    A zipapp is on `sys.path` as itself, and the kernel hands the interpreter the file's path when
    the shebang starts it, so an installed `redteam` is found either way. A checkout, a wheel and a
    `uv run` are none of these and answer `None`: they are updated by whatever installed them.
    """
    for candidate in (sys.argv[0] if sys.argv else "", *sys.path):
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file() and zipfile.is_zipfile(path):
            return path.resolve()
    return None


def token(environment: Mapping[str, str] | None = None) -> str | None:
    """A token for a private repository's releases, when the environment offers one."""
    source = os.environ if environment is None else environment
    for name in TOKEN_VARIABLES:
        value = source.get(name)
        if value:
            return value
    return None


# ---- releases -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Release:
    tag: str
    version: str
    assets: Mapping[str, str]
    """Asset name to the URL this client should download it from."""

    def url(self, name: str) -> str:
        try:
            return self.assets[name]
        except KeyError:
            carried = ", ".join(sorted(self.assets)) or "nothing"
            raise Unavailable(f"{self.tag} carries no {name}; it carries {carried}") from None


def ordinal(text: str) -> tuple[int, ...]:
    """A version as something comparable: the leading numbers, and nothing that follows them."""
    digits = re.findall(r"\d+", text.removeprefix(TAG_PREFIX).removeprefix("v").split("-", 1)[0])
    return tuple(int(part) for part in digits) or (0,)


def is_newer(candidate: str, than: str) -> bool:
    return ordinal(candidate) > ordinal(than)


def transport() -> httpx.BaseTransport | None:
    """How requests leave the process. `None` is the network; a test hands in a mock."""
    return None


def client(*, auth: str | None = None) -> httpx.Client:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if auth:
        headers["Authorization"] = f"Bearer {auth}"
    return httpx.Client(
        base_url=GITHUB_API,
        timeout=TIMEOUT,
        follow_redirects=True,
        headers=headers,
        transport=transport(),
    )


def _releases(http: httpx.Client, page: int) -> list[dict[str, Any]]:
    path = f"/repos/{OWNER}/{REPOSITORY}/releases"
    try:
        response = http.get(path, params={"per_page": PAGE, "page": page})
    except httpx.HTTPError as down:
        raise Unavailable(
            f"{GITHUB_API}{path} did not answer ({type(down).__name__}: {down})"
        ) from down
    if response.is_error:
        raise Unavailable(
            f"{GITHUB_API}{path} answered {response.status_code}; a private repository needs "
            f"{TOKEN_VARIABLES[0]} in the environment"
        )
    return [item for item in response.json() if isinstance(item, dict)]


def _release(published: Mapping[str, Any], *, authenticated: bool) -> Release:
    """One of the API's releases as this client reads it.

    The asset's own API URL is what an authenticated client downloads from -- a private
    repository's `browser_download_url` is not reachable with a token -- and the browser URL is
    what a public one uses, because it does not spend rate limit.
    """
    assets: dict[str, str] = {}
    for asset in published.get("assets") or ():
        name = str(asset.get("name", ""))
        url = str(asset.get("url" if authenticated else "browser_download_url", ""))
        if name and url:
            assets[name] = url
    tag = str(published["tag_name"])
    return Release(tag=tag, version=tag.removeprefix(TAG_PREFIX), assets=assets)


def _ours(page: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for published in page:
        if published.get("draft"):
            continue
        if str(published.get("tag_name", "")).startswith(TAG_PREFIX):
            yield published


def latest(*, auth: str | None = None, make: Maker = client) -> Release:
    """The newest released command line. Other components' tags are not it."""
    with make(auth=auth) as http:
        for page in range(1, PAGES + 1):
            listed = _releases(http, page)
            ours = list(_ours(listed))
            if ours:
                newest = max(ours, key=lambda published: ordinal(str(published["tag_name"])))
                return _release(newest, authenticated=auth is not None)
            if len(listed) < PAGE:
                break
    raise Unavailable(
        f"no {TAG_PREFIX}* release in {OWNER}/{REPOSITORY}; the command line has not been released "
        f"yet, or this token cannot see it"
    )


def at(tag: str, *, auth: str | None = None, make: Maker = client) -> Release:
    """One named release, for an install or an update that pins what it wants."""
    wanted = tag if tag.startswith(TAG_PREFIX) else f"{TAG_PREFIX}{tag.removeprefix('v')}"
    path = f"/repos/{OWNER}/{REPOSITORY}/releases/tags/{wanted}"
    with make(auth=auth) as http:
        try:
            response = http.get(path)
        except httpx.HTTPError as down:
            raise Unavailable(
                f"{GITHUB_API}{path} did not answer ({type(down).__name__}: {down})"
            ) from down
        if response.is_error:
            raise Unavailable(f"no release tagged {wanted} ({response.status_code})")
        return _release(response.json(), authenticated=auth is not None)


# ---- replacing this file ------------------------------------------------------------------------


def fetch(url: str, *, auth: str | None = None, make: Maker = client) -> bytes:
    with make(auth=auth) as http:
        try:
            response = http.get(url, headers={"Accept": "application/octet-stream"})
        except httpx.HTTPError as down:
            raise Unavailable(f"{url} did not answer ({type(down).__name__}: {down})") from down
        if response.is_error:
            raise Unavailable(f"{url} answered {response.status_code}")
        return response.content


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def verify(payload: bytes, published: str, *, name: str) -> None:
    """The asset against the `.sha256` beside it, whose first field is the digest."""
    expected = published.split()[0].strip() if published.split() else ""
    actual = digest(payload)
    if expected and expected != actual:
        raise Corrupt(f"{name}: the download hashes to {actual}, the release publishes {expected}")
    if not zipfile.is_zipfile(io.BytesIO(payload)):
        raise Corrupt(f"{name}: what was downloaded is not a zipapp")


def replace(target: Path, payload: bytes) -> None:
    """Write the new command line beside the old one and rename it over it.

    Beside, so the rename is on one filesystem and therefore atomic: a command line interrupted
    half way through an update is still the command line it was.
    """
    temporary = target.with_name(f".{target.name}.incoming")
    try:
        temporary.write_bytes(payload)
        os.chmod(temporary, os.stat(target).st_mode & 0o7777 if target.exists() else 0o755)
        os.replace(temporary, target)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
