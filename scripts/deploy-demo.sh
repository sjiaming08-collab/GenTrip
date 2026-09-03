#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example. Configure secrets and APP_DOMAIN, then rerun this script." >&2
  exit 1
fi

COMPOSE_FILES="-f docker-compose.yml -f docker-compose.production.yml -f docker-compose.demo.yml"
SERVICES="postgres redis api worker frontend"

# shellcheck disable=SC2086
docker compose $COMPOSE_FILES config --quiet
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES up -d --build $SERVICES
# The importer is idempotent and keeps first-time deployments usable.
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES exec -T api python scripts/import_poi_fixture.py
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES ps $SERVICES
