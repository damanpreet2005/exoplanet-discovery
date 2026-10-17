#!/usr/bin/env bash
#
# exoplanet-discovery deployment script.
#
# This file in the repo is a REFERENCE COPY ONLY, kept here for version
# history and review. It is never executed from this path and pushing a
# change to it does NOT change what runs on the server.
#
# The live, authoritative copy lives at /usr/local/sbin/exoplanet-deploy.sh
# on the Ubuntu server, owned root:root with mode 700. The gha-runner
# account (which GitHub Actions runs as) can neither read nor write that
# file -- it is only allowed, via a narrow sudoers rule, to ask root to
# *execute* it, with no arguments. Updating the live copy after changing
# this reference requires the daman200 account's own sudo rights, done
# deliberately on the server -- see the project's CI/CD setup notes.
#
# Invoked ONLY as: sudo /usr/local/sbin/exoplanet-deploy.sh   (no arguments)

set -euo pipefail

PROJECT_DIR="/home/daman200/projects/exoplanet-discovery"
PROJECT_USER="daman200"
LOCK_FILE="/var/lock/exoplanet-deploy.lock"

# Prevents two deployments from running at the same time even if something
# outside the GitHub Actions concurrency group (e.g. a manual run) overlaps
# with it. flock -n fails fast instead of queuing silently.
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
  echo "ERROR: another deployment is already running. Aborting." >&2
  exit 1
fi

echo "==> [$(date -u +%FT%TZ)] Deployment starting"

# Git operations run as the project's own owner (daman200), not root, so
# file ownership in the project directory never changes and daman200's
# existing SSH credentials are what authenticate to GitHub -- root never
# touches daman200's SSH keys.
echo "==> Checking for unexpected local changes in $PROJECT_DIR"
if [ -n "$(runuser -u "$PROJECT_USER" -- git -C "$PROJECT_DIR" status --porcelain --untracked-files=no)" ]; then
  echo "ERROR: tracked files in $PROJECT_DIR have local modifications." >&2
  echo "Refusing to pull/deploy automatically. Resolve this manually on the server first." >&2
  exit 1
fi

echo "==> Fetching origin/main"
runuser -u "$PROJECT_USER" -- git -C "$PROJECT_DIR" fetch origin main

# --ff-only refuses to move forward if the server's main has diverged from
# origin/main, instead of guessing. It never discards history the way
# `git reset --hard` would.
echo "==> Fast-forwarding main"
runuser -u "$PROJECT_USER" -- git -C "$PROJECT_DIR" merge --ff-only origin/main

cd "$PROJECT_DIR"

echo "==> Validating docker-compose.yml"
docker compose config --quiet

echo "==> Building images for any services with changes"
docker compose build

# `up -d` only recreates containers whose image or configuration actually
# changed. A service with no changes is left running untouched -- this is
# what keeps the frontend/backend/ml-service containers that didn't change
# from being needlessly restarted.
echo "==> Applying (unchanged services are left running)"
docker compose up -d

echo "==> Waiting for services to settle"
sleep 5

check_http() {
  local name="$1" url="$2" attempt
  for attempt in $(seq 1 10); do
    if curl -fsS -o /dev/null --max-time 3 "$url"; then
      echo "    OK: $name ($url)"
      return 0
    fi
    sleep 3
  done
  echo "FAILED: $name did not respond at $url" >&2
  return 1
}

STATUS=0
check_http "ml-service" "http://127.0.0.1:8001/health"        || STATUS=1
check_http "backend"    "http://127.0.0.1:8000/api/v1/health" || STATUS=1
check_http "frontend"   "http://127.0.0.1:5500/"              || STATUS=1

if [ "$STATUS" -ne 0 ]; then
  echo "==> DEPLOYMENT FAILED health checks. Current container state:" >&2
  docker compose ps >&2
  exit 1
fi

echo "==> [$(date -u +%FT%TZ)] Deployment succeeded"
docker compose ps
