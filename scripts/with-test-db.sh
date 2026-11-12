#!/usr/bin/env bash
# Run a command with TEST_DATABASE_URL pointing at a PostgreSQL server.
#
# If TEST_DATABASE_URL is already set (for example in CI), the command runs
# as is. Otherwise this starts a throwaway postgres:16 container (data in
# memory, no volume, a free local port), waits until it accepts connections,
# runs the command, and removes the container afterwards, also on failure.
#
# Usage: scripts/with-test-db.sh <command> [args...]
set -euo pipefail

if [[ -n "${TEST_DATABASE_URL:-}" ]]; then
  exec "$@"
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "with-test-db: Docker is needed to start a test database (or set TEST_DATABASE_URL)" >&2
  exit 1
fi

name="ledgerlens-test-db-$$"
docker run -d --rm --name "$name" \
  --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_USER=ledgerlens -e POSTGRES_PASSWORD=ledgerlens \
  -p 127.0.0.1::5432 postgres:16 >/dev/null
trap 'docker stop "$name" >/dev/null 2>&1 || true' EXIT

for _ in $(seq 1 60); do
  if docker exec "$name" pg_isready -U ledgerlens -h 127.0.0.1 >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$name" pg_isready -U ledgerlens -h 127.0.0.1 >/dev/null

port="$(docker port "$name" 5432/tcp | head -n1 | sed 's/.*://')"
export TEST_DATABASE_URL="postgresql://ledgerlens:ledgerlens@127.0.0.1:${port}/postgres"
echo "with-test-db: using a throwaway PostgreSQL on port ${port}"

"$@"
