#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ ! -f "$REPO_ROOT/docker-compose.yml" || ! -f "$REPO_ROOT/.env.example" ]]; then
  echo "[error] Please run this installer from the Yesterday's Scoop repository checkout."
  exit 1
fi

have_cmd() { command -v "$1" >/dev/null 2>&1; }

require_docker() {
  if ! have_cmd docker; then
    cat <<'MSG'
[error] Docker is not installed.
Install Docker Engine first, then re-run this installer.
Docs: https://docs.docker.com/engine/install/
MSG
    exit 1
  fi

  if ! docker compose version >/dev/null 2>&1; then
    cat <<'MSG'
[error] Docker Compose plugin is missing.
Install Docker Compose plugin, then re-run.
Docs: https://docs.docker.com/compose/install/linux/
MSG
    exit 1
  fi
}

require_writable_dir() {
  local path="$1"
  if ! mkdir -p "$path" >/dev/null 2>&1; then
    echo "[error] Unable to create directory: $path"
    echo "        Choose a writable path for your current user or re-run with appropriate permissions."
    exit 1
  fi

  local probe="$path/.ys_write_test.$$"
  if ! ( : >"$probe" ) >/dev/null 2>&1; then
    echo "[error] Directory is not writable by user $(id -un): $path"
    echo "        Choose a writable path (for example under \$HOME or mounted media with write permissions)."
    exit 1
  fi
  rm -f "$probe"
}

prompt() {
  local var_name="$1"; shift
  local label="$1"; shift
  local default_value="$1"; shift
  local secret="${1:-false}"
  local value

  if [[ "$secret" == "true" ]]; then
    read -r -s -p "$label [$default_value]: " value
    echo
  else
    read -r -p "$label [$default_value]: " value
  fi

  if [[ -z "$value" ]]; then
    value="$default_value"
  fi
  printf -v "$var_name" '%s' "$value"
}

rand_secret() {
  if have_cmd openssl; then
    openssl rand -hex 24
  else
    tr -dc 'A-Za-z0-9' </dev/urandom | head -c 48
  fi
}

set_env_value() {
  local file="$1" key="$2" value="$3"
  if grep -qE "^${key}=" "$file"; then
    sed -i "s|^${key}=.*$|${key}=${value}|" "$file"
  else
    echo "${key}=${value}" >>"$file"
  fi
}

echo "== Yesterday's Scoop installer (Linux) =="
require_docker

DEFAULT_INSTALL_DIR="$HOME/yesterdays-scoop"
DEFAULT_DATA_ROOT="$HOME/yesterdays-scoop-data"
DEFAULT_APP_PORT="8000"
DEFAULT_MINIFLUX_PORT="8080"
DEFAULT_MEILI_PORT="7700"
DEFAULT_ADMIN_USER="admin"

prompt INSTALL_DIR "Install directory" "$DEFAULT_INSTALL_DIR"
prompt APP_PORT "App port" "$DEFAULT_APP_PORT"
prompt MINIFLUX_PORT "Miniflux port (optional)" "$DEFAULT_MINIFLUX_PORT"
prompt MEILI_PORT "Meilisearch port (optional)" "$DEFAULT_MEILI_PORT"
prompt DATA_ROOT "Persistent data path" "$DEFAULT_DATA_ROOT"
prompt ADMIN_USER "Initial admin username" "$DEFAULT_ADMIN_USER"
prompt ADMIN_PASS "Initial admin password" "$(rand_secret)" true
prompt AUTH_SECRET "App auth secret" "$(rand_secret)" true
prompt APP_DB_PASSWORD "App DB password" "$(rand_secret)" true
prompt MINIFLUX_DB_PASSWORD "Miniflux DB password" "$(rand_secret)" true
prompt MINIFLUX_ADMIN_PASSWORD "Miniflux admin password" "$(rand_secret)" true
prompt MEILI_MASTER_KEY "Meilisearch master key" "$(rand_secret)" true

if [[ -z "$ADMIN_PASS" || -z "$AUTH_SECRET" || -z "$APP_DB_PASSWORD" || -z "$MINIFLUX_DB_PASSWORD" || -z "$MEILI_MASTER_KEY" ]]; then
  echo "[error] Required values cannot be empty."
  exit 1
fi

require_writable_dir "$INSTALL_DIR"
require_writable_dir "$DATA_ROOT"
mkdir -p "$DATA_ROOT"/{app_db,miniflux_db,redis,meili,ollama}

if [[ "$INSTALL_DIR" != "$REPO_ROOT" ]]; then
  echo "[info] Copying application files to $INSTALL_DIR"
  if have_cmd rsync; then
    rsync -a --delete --exclude '.git' --exclude '.venv' --exclude '__pycache__' --exclude 'data' "$REPO_ROOT/" "$INSTALL_DIR/"
  else
    cp -a "$REPO_ROOT/." "$INSTALL_DIR/"
  fi
fi

ENV_FILE="$INSTALL_DIR/.env"
cp "$INSTALL_DIR/.env.example" "$ENV_FILE"

set_env_value "$ENV_FILE" "YS_WEB_PORT" "$APP_PORT"
set_env_value "$ENV_FILE" "YS_MINIFLUX_PORT" "$MINIFLUX_PORT"
set_env_value "$ENV_FILE" "YS_MEILI_PORT" "$MEILI_PORT"
set_env_value "$ENV_FILE" "YS_DATA_ROOT" "$DATA_ROOT"
set_env_value "$ENV_FILE" "INITIAL_ADMIN_USERNAME" "$ADMIN_USER"
set_env_value "$ENV_FILE" "INITIAL_ADMIN_PASSWORD" "$ADMIN_PASS"
set_env_value "$ENV_FILE" "AUTH_SECRET" "$AUTH_SECRET"
set_env_value "$ENV_FILE" "APP_DB_PASSWORD" "$APP_DB_PASSWORD"
set_env_value "$ENV_FILE" "DATABASE_URL" "postgresql+psycopg://scoop:${APP_DB_PASSWORD}@app_db:5432/scoop"
set_env_value "$ENV_FILE" "MINIFLUX_DB_PASSWORD" "$MINIFLUX_DB_PASSWORD"
set_env_value "$ENV_FILE" "MINIFLUX_DATABASE_URL" "postgres://miniflux:${MINIFLUX_DB_PASSWORD}@miniflux_db:5432/miniflux?sslmode=disable"
set_env_value "$ENV_FILE" "MINIFLUX_ADMIN_PASSWORD" "$MINIFLUX_ADMIN_PASSWORD"
set_env_value "$ENV_FILE" "MEILI_MASTER_KEY" "$MEILI_MASTER_KEY"

pushd "$INSTALL_DIR" >/dev/null

echo "[info] Starting stack..."
docker compose up -d --build

popd >/dev/null

cat <<MSG

✅ Yesterday's Scoop is starting.

Open in browser:
  http://localhost:${APP_PORT}

Next steps:
  1) Open the URL above.
  2) Complete the web setup wizard.
  3) Configure sources/AI/social context from the admin UI.

Install location: $INSTALL_DIR
Data path:        $DATA_ROOT

MSG
