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


def brain_dir() -> Path:
    """Absolute path to the brain directory."""
    return Path(os.environ.get(BRAIN_DIR_ENV, DEFAULT_BRAIN_DIR)).resolve()


def vitruvio_bin() -> str:
    """Name or path of the vitruvio executable."""
    return os.environ.get(VITRUVIO_BIN_ENV, DEFAULT_VITRUVIO_BIN)
