"""populate / snapshot / restore against Gitea's real on-disk state.

The property that matters for RL: an episode can mutate the app, be rewound to
an earlier checkpoint, and reset back to the deterministic baseline.

Two reset paths are exercised:
  * a fast API reseed (delete + recreate the world) — no process restart;
  * the on-disk seam (snapshot/restore the real db + repos) — the fallback for
    an app with no reset API, and how you rewind to an arbitrary checkpoint.
"""

from __future__ import annotations

import shutil

from sandbox import seed, state
from sandbox.config import settings
from sandbox.gitea_client import GiteaClient


def test_api_reseed_is_deterministic(fresh):
    """Reseeding returns the world to exactly the baseline set of repos."""
    before = {r["full_name"] for r in fresh.list_repos()}
    fresh.create_repo("scratch-repo")
    assert any(r["full_name"].endswith("scratch-repo") for r in fresh.list_repos())

    seed.seed_baseline(fresh)  # fast API reseed — no process restart
    after = {r["full_name"] for r in fresh.list_repos()}
    assert after == before
    assert not any(r.endswith("scratch-repo") for r in after)


def test_snapshot_restore_on_disk(app, fresh):
    """Snapshot the real db+repos, mutate away, then swap the files back.

    Stops/starts the app so the on-disk state is swapped safely under a quiesced
    process — the reproducibility guarantee an RL episode depends on.
    """
    client = GiteaClient()
    client.create_repo("checkpoint-repo")
    state.snapshot("mid")                        # capture db + repos to disk

    seed.seed_baseline(client)                   # reset → checkpoint repo gone
    assert not any(r["full_name"].endswith("checkpoint-repo")
                   for r in GiteaClient().list_repos())

    state.restore(app, "mid")                    # swap the on-disk state back
    assert any(r["full_name"].endswith("checkpoint-repo")
               for r in GiteaClient().list_repos())

    shutil.rmtree(settings.snapshot_dir / "mid", ignore_errors=True)
