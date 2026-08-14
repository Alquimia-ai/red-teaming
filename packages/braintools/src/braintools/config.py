"""Brain-tooling settings, resolved from environment. Nothing here reaches the network
— it only decides where the brain and the vitruvio executable are.
"""

from __future__ import annotations

import os
from pathlib import Path

# Where the Boltzmann brain lives on disk. Recreate it with `braintools init`.
BRAIN_DIR_ENV = "BRAINTOOLS_BRAIN_DIR"
DEFAULT_BRAIN_DIR = "brain"

# The vitruvio CLI executable (installed via the official install.sh).
VITRUVIO_BIN_ENV = "BRAINTOOLS_VITRUVIO_BIN"
DEFAULT_VITRUVIO_BIN = "vitruvio"

# OCI registry the brain publishes to / pulls from (shared config).
REGISTRY_ENV = "BRAINTOOLS_REGISTRY"
DEFAULT_REGISTRY = "ghcr.io/alquimia-ai/red-teaming-brain"

# Where `braintools seed` reads source documents from. Each immediate subdirectory is a
# subject: docs/sources/roastme/* -> subject "roastme", docs/sources/sparring/* -> "sparring".
SOURCES_DIR_ENV = "BRAINTOOLS_SOURCES_DIR"
DEFAULT_SOURCES_DIR = "packages/braintools/docs/sources"

# The committed pin (reference + tag + digest) so collaborators pull one version.
LOCK_FILE = "brain.lock"


def brain_dir() -> Path:
    """Absolute path to the brain directory."""
    return Path(os.environ.get(BRAIN_DIR_ENV, DEFAULT_BRAIN_DIR)).resolve()


def vitruvio_bin() -> str:
    """Name or path of the vitruvio executable."""
    return os.environ.get(VITRUVIO_BIN_ENV, DEFAULT_VITRUVIO_BIN)


def registry_reference() -> str:
    return os.environ.get(REGISTRY_ENV, DEFAULT_REGISTRY)


def sources_dir() -> Path:
    return Path(os.environ.get(SOURCES_DIR_ENV, DEFAULT_SOURCES_DIR)).resolve()


def lock_path() -> Path:
    return Path(LOCK_FILE).resolve()
