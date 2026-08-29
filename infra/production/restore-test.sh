#!/usr/bin/env bash
#
# Restores the production database into a throwaway instance and proves the data came back.
#
# This is the one thing `verify-production.sh` cannot do. That script reads the backup *settings*
# and confirms the most recent backup completed, which is a real check and is not the same claim
# as "we can get the data back". An untested restore is a plan, not a capability, and the two are
# only distinguishable by doing it. NFR-10 asks for the capability.
#
#   ./infra/production/restore-test.sh <project-id> [region]
#
# What it does, in order:
#
#   1. finds the most recent successful backup of the production instance;
#   2. creates a temporary instance and restores that backup into it;
#   3. connects and asserts the restored data is genuinely there and internally consistent -
#      transactions exist, the audit trail exists, and an approved transaction still has the
#      approval row that approved it;
#   4. deletes the temporary instance.
#
# It never touches the production instance. Every write it makes is to the temporary one, and the
# restore source is a backup rather than the live database.
#
# Run it before go-live, and on a schedule thereafter. A restore that worked six months ago is
# evidence about six months ago.

set -uo pipefail

PROJECT="${1:?usage: restore-test.sh <project-id> [region]}"
REGION="${2:-me-central1}"
SOURCE="agfze-primary"
# Stamped rather than fixed, so a previous run that died before its cleanup cannot collide with
# this one, and so an instance left behind is obviously dated.
TARGET="agfze-restore-test-$(date -u +%Y%m%d-%H%M%S)"
DB="agfze"

failures=0
checks=0

pass() { checks=$((checks + 1)); printf '  \033[32mok\033[0m    %s\n' "$1"; }
fail() {
  checks=$((checks + 1))
  failures=$((failures + 1))
  printf '  \033[31mFAIL\033[0m  %s\n        expected: %s\n' "$1" "$2"
}
note() { printf '        %s\n' "$1"; }

cleanup() {
  # Runs on every exit path, including a failed restore and a Ctrl-C, because a forgotten test
  # instance holding a copy of production data is a genuine security problem rather than untidiness.
  if gcloud sql instances describe "$TARGET" --project "$PROJECT" >/dev/null 2>&1; then
    echo
    echo "Removing the temporary instance ${TARGET}"
    gcloud sql instances delete "$TARGET" --project "$PROJECT" --quiet >/dev/null 2>&1 \
      && echo "  removed" \
      || echo "  COULD NOT REMOVE - delete ${TARGET} by hand, it holds a copy of production data"
  fi
}
trap cleanup EXIT INT TERM

echo "Restore test for ${SOURCE} in ${PROJECT} (${REGION})"
echo

# --- 1 the backup to restore from -------------------------------------------------------------
echo "Choosing a backup"

backup_id=$(gcloud sql backups list --instance "$SOURCE" --project "$PROJECT" \
  --filter 'status=SUCCESSFUL' --sort-by '~windowStartTime' --limit 1 \
  --format 'value(id)' 2>/dev/null)

if [ -z "$backup_id" ]; then
  fail "a successful backup exists to restore from" "none found for ${SOURCE}"
  echo
  echo "${checks} checks, ${failures} failed."
  exit 1
fi

backup_time=$(gcloud sql backups describe "$backup_id" --instance "$SOURCE" --project "$PROJECT" \
  --format 'value(windowStartTime)' 2>/dev/null)
pass "restoring backup ${backup_id} taken at ${backup_time}"

# --- 2 the throwaway instance ------------------------------------------------------------------
echo
echo "Creating the temporary instance"
note "this takes several minutes; it is a real Cloud SQL instance"

# Deliberately the smallest tier and zonal: this instance exists for minutes and serves one
# connection. Matching production's tier would cost real money to prove nothing extra.
if ! gcloud sql instances create "$TARGET" \
  --project "$PROJECT" \
  --database-version POSTGRES_15 \
  --tier db-custom-1-3840 \
  --region "$REGION" \
  --availability-type ZONAL \
  --no-backup \
  --quiet >/dev/null 2>&1; then
  fail "the temporary instance was created" "gcloud sql instances create failed"
  echo
  echo "${checks} checks, ${failures} failed."
  exit 1
fi
pass "temporary instance ${TARGET} created"

# --- 3 the restore ------------------------------------------------------------------------------
echo
echo "Restoring"

if ! gcloud sql backups restore "$backup_id" \
  --restore-instance "$TARGET" \
  --backup-instance "$SOURCE" \
  --project "$PROJECT" \
  --quiet >/dev/null 2>&1; then
  fail "the backup restored into the temporary instance" "gcloud sql backups restore failed"
  echo
  echo "${checks} checks, ${failures} failed."
  exit 1
fi
pass "backup ${backup_id} restored into ${TARGET}"

# --- 4 what actually came back --------------------------------------------------------------------
#
# The point of the whole exercise. A restore that completes and leaves empty tables is a restore
# that did not work, and the only way to know the difference is to read the data.

echo
echo "Reading the restored data"

query() {
  gcloud sql connect "$TARGET" --project "$PROJECT" --user postgres --database "$DB" \
    --quiet <<SQL 2>/dev/null | tr -d ' \r'
\\t
\\a
$1
SQL
}

expect_positive() {
  local label="$1" value="$2"
  if [ -n "$value" ] && [ "$value" -gt 0 ] 2>/dev/null; then
    pass "${label} (${value})"
  else
    fail "${label}" "a row count above zero, found '${value:-nothing}'"
  fi
}

expect_positive "transactions came back" "$(query 'SELECT count(*) FROM trade_transactions;')"
expect_positive "the audit trail came back" "$(query 'SELECT count(*) FROM audit_events;')"
expect_positive "documents came back" "$(query 'SELECT count(*) FROM documents;')"

# Referential integrity, not just row counts. A transaction that reached Approved and has no
# approval row behind it would mean the restore tore the two apart, which row counts alone would
# never show.
orphans=$(query "
  SELECT count(*) FROM trade_transactions t
  WHERE t.status IN ('approved', 'integration_pending', 'committed')
    AND NOT EXISTS (
      SELECT 1 FROM approval_tasks a
      WHERE a.transaction_id = t.id AND a.decision = 'approved'
    );")
if [ "$orphans" = "0" ]; then
  pass "every approved transaction still has the approval that approved it"
else
  fail "every approved transaction still has its approval row" "${orphans} have none"
fi

# The migration history, so the restored schema is a version this application can actually run
# against rather than an older one nobody noticed.
revision=$(query 'SELECT version_num FROM alembic_version;')
if [ -n "$revision" ]; then
  pass "the schema is at migration ${revision}"
  note "compare this against the revision the running application expects"
else
  fail "the restored database records its migration revision" "alembic_version is empty"
fi

echo
echo "${checks} checks, ${failures} failed."
[ "$failures" -eq 0 ] || exit 1

echo
echo "The backup restores and the data is intact. Record the date of this run - a restore that"
echo "worked six months ago is evidence about six months ago."
