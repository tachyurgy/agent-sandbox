#!/usr/bin/env bash
# Stop the sandbox's Gitea instance.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONF="$ROOT/vendor/gitea-home/custom/conf/app.ini"
pkill -f "$CONF" 2>/dev/null && echo "stopped" || echo "not running"
