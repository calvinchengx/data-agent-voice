# Importing the addon is what registers it. An empty __init__.py leaves the
# extension present on disk, structurally identical to a working one, and
# invisible to the runtime -- "Failed to load the addon using all addon
# loaders", with no traceback, because nothing was ever imported to fail.
from . import addon

__all__ = ["addon"]
