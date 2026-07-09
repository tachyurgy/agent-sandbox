"""Lifecycle control of the real application under test (Gitea).

Integrating an app into a sandbox means *owning its process* — you have to be
able to start it, wait for it to be genuinely ready, and stop it cleanly so its
on-disk state can be snapshotted consistently. Real apps don't hand you an
"admin reset" endpoint; controlling the process is how you get determinism.
"""

from __future__ import annotations

import signal
import subprocess
import time
from pathlib import Path
from typing import Optional

import httpx

from .config import settings


class GiteaApp:
    """Start/stop the vendored Gitea binary against a SQLite work dir."""

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None

    # -- process control ----------------------------------------------------

    def start(self, wait: bool = True, timeout: float = 30.0) -> None:
        if self.is_up():
            return
        if not settings.binary.exists():
            raise RuntimeError(
                f"Gitea binary missing at {settings.binary}. Run scripts/start_app.sh."
            )
        log = open(settings.work_dir / "gitea.run.log", "ab")
        self._proc = subprocess.Popen(
            [str(settings.binary), "web", "-c", str(settings.config_file)],
            stdout=log,
            stderr=log,
            # Own process group so we can kill children (gitea spawns helpers).
            start_new_session=True,
        )
        if wait:
            self.wait_until_ready(timeout)

    def stop(self, timeout: float = 15.0) -> None:
        """Stop whatever is serving on the port, whether we started it or not."""
        if self._proc is not None:
            self._terminate_group(self._proc)
            self._proc = None
        # Belt and suspenders: also kill any instance on our config path, in case
        # a prior start left a stray process holding the port.
        self._stop_external()
        # Wait for the port to actually free up. Raise if it doesn't — callers
        # (restore) swap the DB on disk and MUST NOT do so under a live process.
        deadline = time.time() + timeout
        while self.is_up() and time.time() < deadline:
            time.sleep(0.2)
        if self.is_up():
            raise RuntimeError("app did not stop; refusing to touch its state on disk")

    def _terminate_group(self, proc: subprocess.Popen) -> None:
        try:
            import os

            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                import os

                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _stop_external(self) -> None:
        import os
        import re

        # Match the gitea web process for THIS instance by its config-file path
        # (unique per work dir) — robust whether it was launched via an absolute
        # or relative binary path.
        out = subprocess.run(
            ["pgrep", "-f", str(settings.config_file)],
            capture_output=True,
            text=True,
        ).stdout
        for pid in re.findall(r"\d+", out):
            try:
                os.kill(int(pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass

    # -- readiness ----------------------------------------------------------

    def is_up(self) -> bool:
        try:
            r = httpx.get(f"{settings.base_url}/api/v1/version", timeout=1.5)
            return r.status_code == 200
        except Exception:
            return False

    def wait_until_ready(self, timeout: float = 30.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_up():
                return
            time.sleep(0.3)
        raise TimeoutError(f"Gitea did not become ready within {timeout}s")

    # -- context manager ----------------------------------------------------

    def __enter__(self) -> "GiteaApp":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
