"""populate / snapshot / restore against a REAL app's on-disk state.

Gitea was never designed to be reset between runs — there is no admin "wipe"
endpoint. So the state seam is the one every real integration comes down to:
the app's actual persistence. For Gitea that's the SQLite database plus the
on-disk git repositories directory. Capturing and swapping those two, with the
app quiesced, is what makes an episode reproducible.

    populate(app)          -> restore the deterministic baseline snapshot
    snapshot(name)         -> consistent copy of db + repos to snapshots/<name>
    restore(app, name)     -> stop app, swap in the snapshot, start app

`snapshot` uses SQLite's online backup API so the DB copy is transactionally
consistent even if taken while the app is idle-but-running; `restore` stops the
app first because you cannot swap files under a live process safely.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .config import settings

if TYPE_CHECKING:
    from .app_process import GiteaApp


def _snapshot_path(name: str) -> Path:
    return settings.snapshot_dir / name


def has_snapshot(name: str) -> bool:
    p = _snapshot_path(name)
    return (p / "gitea.db").exists()


def _backup_db(src: Path, dst: Path) -> None:
    """Transactionally-consistent copy of the SQLite file (online backup API)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(str(src))
    target = sqlite3.connect(str(dst))
    try:
        with target:
            source.backup(target)
    finally:
        source.close()
        target.close()


def snapshot(name: str) -> dict:
    """Capture the full app state (db + repos) into snapshots/<name>/."""
    dest = _snapshot_path(name)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    _backup_db(settings.db_path, dest / "gitea.db")

    repos_dest = dest / "gitea-repositories"
    if settings.repos_path.exists():
        shutil.copytree(settings.repos_path, repos_dest)
    else:
        repos_dest.mkdir()

    manifest = {
        "name": name,
        "repo_count": _count_repos(dest / "gitea-repositories"),
        "db_bytes": (dest / "gitea.db").stat().st_size,
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def restore(app: "GiteaApp", name: str) -> dict:
    """Stop the app, swap in snapshot <name>, restart. Returns the manifest."""
    src = _snapshot_path(name)
    if not (src / "gitea.db").exists():
        raise FileNotFoundError(f"no snapshot named {name!r} in {settings.snapshot_dir}")

    was_up = app.is_up()
    app.stop()

    # Replace the database — clear any stale WAL/SHM sidecar files first so the
    # restored db isn't shadowed by a leftover write-ahead log.
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(settings.db_path) + suffix)
        if p.exists():
            p.unlink()
    shutil.copy2(src / "gitea.db", settings.db_path)
    settings.db_path.chmod(0o644)  # ensure the restored db is writable

    # Replace the repositories directory wholesale.
    if settings.repos_path.exists():
        shutil.rmtree(settings.repos_path)
    shutil.copytree(src / "gitea-repositories", settings.repos_path)

    if was_up:
        app.start()

    return json.loads((src / "manifest.json").read_text())


def populate(client=None) -> dict:  # noqa: ANN001
    """Reset the app to the deterministic baseline world for a fresh episode.

    Two reset strategies live in this module, and choosing between them is the
    real judgment call when integrating an app:

      * ``populate`` uses the app's OWN API (delete repos, re-seed the world) —
        fast, no process restart, ideal for per-episode resets when the app
        exposes enough API to rebuild a known state.
      * ``restore`` swaps the on-disk state — the fallback for apps that give you
        no programmatic reset, and the way to rewind to an *arbitrary* checkpoint.
    """
    from .gitea_client import GiteaClient  # deferred to avoid an import cycle
    from .seed import seed_baseline

    client = client or GiteaClient()
    return seed_baseline(client)


def _count_repos(repos_dir: Path) -> int:
    if not repos_dir.exists():
        return 0
    # Gitea stores repos as <owner>/<repo>.git
    return sum(1 for _ in repos_dir.glob("*/*.git"))
