#!/usr/bin/env bash
# Bring up the real application under test (Gitea) from nothing, reproducibly:
# download the binary, generate config, init the DB, create an admin + API token,
# boot it, then seed the deterministic baseline world.
#
# Idempotent: re-running reuses an existing install and just ensures it's up.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR="$ROOT/vendor"
HOME_DIR="$VENDOR/gitea-home"
CONF="$HOME_DIR/custom/conf/app.ini"
BIN="$VENDOR/gitea"
PORT="${GITEA_PORT:-3000}"
ADMIN_USER="${GITEA_ADMIN_USER:-sandbox}"
ADMIN_PASS="${GITEA_ADMIN_PASSWORD:-sandboxpass123}"

mkdir -p "$HOME_DIR/custom/conf" "$HOME_DIR/data"

# 1. binary
if [ ! -x "$BIN" ]; then
  VER=$(curl -s https://dl.gitea.com/gitea/version.json | python3 -c "import sys,json;print(json.load(sys.stdin)['latest']['version'])")
  OS=$(uname -s | tr '[:upper:]' '[:lower:]'); ARCH=$(uname -m)
  [ "$ARCH" = "arm64" ] && ARCH="arm64" || ARCH="amd64"
  ASSET="gitea-${VER}-${OS}-10.12-arm64"
  [ "$OS" = "linux" ] && ASSET="gitea-${VER}-linux-${ARCH}"
  echo "downloading Gitea ${VER} ($ASSET) ..."
  curl -sL "https://dl.gitea.com/gitea/${VER}/${ASSET}" -o "$BIN"
  chmod +x "$BIN"; xattr -d com.apple.quarantine "$BIN" 2>/dev/null || true
fi

# 2. config
if [ ! -f "$CONF" ]; then
  SECRET=$("$BIN" generate secret SECRET_KEY)
  INTERNAL=$("$BIN" generate secret INTERNAL_TOKEN)
  cat > "$CONF" <<EOF
APP_NAME = Agent Sandbox Gitea
RUN_MODE = prod
WORK_PATH = $HOME_DIR
[server]
HTTP_ADDR = 127.0.0.1
HTTP_PORT = $PORT
ROOT_URL = http://127.0.0.1:$PORT/
DISABLE_SSH = true
OFFLINE_MODE = true
START_SSH_SERVER = false
[database]
DB_TYPE = sqlite3
PATH = $HOME_DIR/data/gitea.db
[repository]
ROOT = $HOME_DIR/data/gitea-repositories
[security]
INSTALL_LOCK = true
SECRET_KEY = $SECRET
INTERNAL_TOKEN = $INTERNAL
PASSWORD_HASH_ALGO = pbkdf2
[service]
DISABLE_REGISTRATION = true
[log]
MODE = console
LEVEL = warn
[cron]
ENABLED = false
EOF
fi

# 3. schema + admin user (idempotent)
"$BIN" migrate -c "$CONF" >/dev/null 2>&1 || true
"$BIN" admin user create --admin --username "$ADMIN_USER" --password "$ADMIN_PASS" \
  --email "$ADMIN_USER@example.com" --must-change-password=false -c "$CONF" 2>/dev/null \
  || echo "admin user already exists"

# 4. boot
if ! curl -sf "http://127.0.0.1:$PORT/api/v1/version" >/dev/null 2>&1; then
  "$BIN" web -c "$CONF" >"$HOME_DIR/gitea.run.log" 2>&1 &
  for i in $(seq 1 30); do
    curl -sf "http://127.0.0.1:$PORT/api/v1/version" >/dev/null 2>&1 && break
    sleep 0.5
  done
fi
echo "gitea up: $(curl -s http://127.0.0.1:$PORT/api/v1/version)"

# 5. API token (mint once, store where config.token() looks)
TOKF="$HOME_DIR/harness_token.txt"
if [ ! -s "$TOKF" ]; then
  curl -s -u "$ADMIN_USER:$ADMIN_PASS" -X POST "http://127.0.0.1:$PORT/api/v1/users/$ADMIN_USER/tokens" \
    -H "Content-Type: application/json" \
    -d '{"name":"harness","scopes":["write:repository","write:issue","write:user","write:organization"]}' \
    | python3 -c "import sys,json;open('$TOKF','w').write(json.load(sys.stdin)['sha1'])"
  echo "minted API token -> $TOKF"
fi

echo "done. Next: python -m sandbox.seed  (seed the baseline world)"
