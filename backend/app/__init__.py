import os

__version__ = "0.1.0"


def release_version() -> str:
    """The package version plus the Cloud Run revision serving it, if any.

    ``__version__`` only moves when someone bumps it, but every deploy is a new
    revision; usage rows need to tell deploys apart.
    """
    revision = os.environ.get("K_REVISION", "").strip()
    return f"{__version__}+{revision}" if revision else __version__
