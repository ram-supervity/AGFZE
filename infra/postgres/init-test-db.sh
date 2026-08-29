#!/bin/sh
set -e

# Executed once by the postgres entrypoint, against the freshly initialised cluster.
# \gexec keeps it idempotent: CREATE DATABASE has no IF NOT EXISTS form.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
SELECT 'CREATE DATABASE agfze_test OWNER agfze'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'agfze_test')\gexec
SQL
