"""Environment-driven configuration for the sandbox.

Nothing here is app-specific beyond Gitea's paths — swap the target app and
only these values change. Secrets (the API token, admin password) come from the
environment or the token file the start script writes; they are never hard-coded
(a lesson worth taking seriously in this line of work).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR = REPO_ROOT / "vendor"


@dataclass(frozen=True)
class Settings:
    # The target application under integration (real OSS app: Gitea).
    base_url: str = os.environ.get("GITEA_URL", "http://127.0.0.1:3000")
    admin_user: str = os.environ.get("GITEA_ADMIN_USER", "sandbox")
    admin_password: str = os.environ.get("GITEA_ADMIN_PASSWORD", "sandboxpass123")

    # Where the app binary + its runtime state live.
    binary: Path = VENDOR / "gitea"
    work_dir: Path = VENDOR / "gitea-home"

    # Snapshot store.
    snapshot_dir: Path = REPO_ROOT / "snapshots"
    fixture: str = os.environ.get("SANDBOX_FIXTURE", "baseline")

    http_timeout: float = float(os.environ.get("GITEA_HTTP_TIMEOUT", "15"))

    # MCP transport.
    mcp_transport: str = os.environ.get("MCP_TRANSPORT", "stdio")
    mcp_host: str = os.environ.get("MCP_HOST", "0.0.0.0")
    mcp_port: int = int(os.environ.get("MCP_PORT", "9100"))

    @property
    def config_file(self) -> Path:
        return self.work_dir / "custom" / "conf" / "app.ini"

    @property
    def db_path(self) -> Path:
        return self.work_dir / "data" / "gitea.db"

    @property
    def repos_path(self) -> Path:
        return self.work_dir / "data" / "gitea-repositories"

    def token(self) -> str:
        """API token: env first, then the file the start script wrote."""
        tok = os.environ.get("GITEA_TOKEN")
        if tok:
            return tok
        tok_file = self.work_dir / "harness_token.txt"
        if tok_file.exists():
            return tok_file.read_text().strip()
        raise RuntimeError(
            "No Gitea API token. Run scripts/start_app.sh, or set GITEA_TOKEN."
        )


settings = Settings()
