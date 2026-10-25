#!/usr/bin/env bash
# DVT's ibis 12 engine system tests on Docker: Oracle, SQL Server, Postgres, MySQL, Trino,
# ClickHouse and DuckDB. Usage: [KEEP=1] tests/system/ibis12/run.sh [pytest args]
# KEEP=1 leaves the engines up for the next run (the tests reload their tables).
set -euo pipefail
cd "$(dirname "$0")"
[ -n "${KEEP:-}" ] || trap 'docker compose --profile run down -v --remove-orphans >/dev/null 2>&1' EXIT
docker compose up -d --wait --wait-timeout 900
docker compose --profile run run --rm --build runner \
    python -m pytest -p no:cacheprovider tests/system/ibis12 "$@"
