"""Copy backend source into Wrangler's isolated Python module root."""

from pathlib import Path
from shutil import copy2, copytree, rmtree

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PACKAGE = REPOSITORY_ROOT / "server"
WORKER_PACKAGE = REPOSITORY_ROOT / "cloudflare_worker" / "server"


def prepare_worker_source() -> None:
    if WORKER_PACKAGE.exists():
        rmtree(WORKER_PACKAGE)

    WORKER_PACKAGE.mkdir(parents=True)
    copy2(SOURCE_PACKAGE / "__init__.py", WORKER_PACKAGE / "__init__.py")
    copytree(
        SOURCE_PACKAGE / "app",
        WORKER_PACKAGE / "app",
        ignore=lambda _directory, names: {
            name for name in names if name == "__pycache__" or name.endswith(".pyc")
        },
    )


if __name__ == "__main__":
    prepare_worker_source()
