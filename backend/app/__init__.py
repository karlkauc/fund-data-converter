import os

__version__ = "0.1.0"


def release_version() -> str:
    """The package version plus the Cloud Run revision serving it, if any.

    ``__version__`` only moves when someone bumps it, but every deploy is a new
    revision; usage rows and converted files need to tell deploys apart. On the
    VPS the built commit (``GIT_COMMIT``) stands in for the revision.
    """
    revision = os.environ.get("K_REVISION", "").strip() or os.environ.get("GIT_COMMIT", "").strip()[:7]
    return f"{__version__}+{revision}" if revision else __version__
