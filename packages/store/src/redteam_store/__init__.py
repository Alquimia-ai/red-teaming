"""The object store: append-only, content-addressed where it helps, and the only stateful piece.

`layout` is re-exported because every component builds keys through it and nothing else should know
how a key is spelled.
"""

from redteam_store import layout
from redteam_store.interface import ObjectAlreadyExists, ObjectNotFound, ObjectStore

__all__ = ["ObjectAlreadyExists", "ObjectNotFound", "ObjectStore", "layout"]
