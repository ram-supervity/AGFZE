#!/usr/bin/env bash
#
# Reads the production estate back out of the live project and fails if anything this step
# promised is not actually configured.
#
# Terraform proves what was applied once. This proves what is true now - which is a different
# question, and the one that matters the morning somebody turns a setting off by hand to debug
# something and forgets to turn it back on. Section 13 of this step's specification says never to
# treat a managed-service default as assumed, and this script is how that instruction is kept:
# every check below reads a real value from a real API.
#
#   ./infra/production/verify-production.sh <project-id> [region]
#
# Exit code 0 means every check passed. Anything else means at least one did not, and the failing
# checks are listed. Intended to be run after `terraform apply`, before a go-live sign-off, and on
# a schedule thereafter.

set -uo pipefail

PROJECT="${1:?usage: verify-production.sh <project-id> [region]}"
REGION="${2:-me-central1}"
INSTANCE="agfze-primary"
BUCKET="${PROJECT}-agfze-documents"
BACKEND="agfze-backend"
FRONTEND="agfze-frontend"

failures=0
checks=0

pass() { checks=$((checks + 1)); printf '  \033[32mok\033[0m    %s\n' "$1"; }
fail() {
  checks=$((checks + 1))
  failures=$((failures + 1))
  printf '  \033[31mFAIL\033[0m  %s\n' "$1"
  [ -n "${2:-}" ] && printf '        %s\n' "$2"
}

expect() { # expect <description> <actual> <wanted>
  if [ "$2" = "$3" ]; then pass "$1"; else fail "$1" "expected '$3', found '$2'"; fi
}

sql() { gcloud sql instances describe "$INSTANCE" --project "$PROJECT" --format "value($1)" 2>/dev/null; }
run() { gcloud run services describe "$2" --project "$PROJECT" --region "$REGION" --format "value($1)" 2>/dev/null; }

echo
echo "AGFZE Command Centre - production verification"
echo "project ${PROJECT}, region ${REGION}"
echo

# --- 8.5 transport ------------------------------------------------------------------------------
echo "Transport"

policy=$(gcloud compute ssl-policies describe agfze-modern-tls --project "$PROJECT" \
  --format 'value(minTlsVersion)' 2>/dev/null)
expect "TLS 1.2 is the floor at the edge" "$policy" "TLS_1_2"

redirect=$(gcloud compute url-maps describe agfze-https-redirect --project "$PROJECT" \
  --format 'value(defaultUrlRedirect.httpsRedirect)' 2>/dev/null)
expect "plain HTTP redirects to HTTPS and serves nothing" "$redirect" "True"

for service in "$BACKEND" "$FRONTEND"; do
  ingress=$(run "ingress" "$service")
  expect "${service} answers only through the load balancer" "$ingress" \
    "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
done

# --- 8.5 encryption at rest ------------------------------------------------------------------
echo
echo "Encryption at rest"

db_key=$(sql "diskEncryptionConfiguration.kmsKeyName")
if [ -n "$db_key" ]; then
  pass "the database is encrypted with a key AGFZE owns (${db_key##*/})"
else
  fail "the database is encrypted with a customer-managed key" \
    "no CMEK is set - the instance falls back to a Google-managed key, which is encryption but not revocable by AGFZE"
fi

bucket_key=$(gcloud storage buckets describe "gs://${BUCKET}" --project "$PROJECT" \
  --format 'value(default_kms_key)' 2>/dev/null)
if [ -n "$bucket_key" ]; then
  pass "the document store is encrypted with a key AGFZE owns"
else
  fail "the document store is encrypted with a customer-managed key" "no default KMS key on the bucket"
fi

public=$(gcloud storage buckets describe "gs://${BUCKET}" --project "$PROJECT" \
  --format 'value(public_access_prevention)' 2>/dev/null)
expect "no document can ever be made public" "$public" "enforced"

# --- 11 private connectivity --------------------------------------------------------------------
echo
echo "Connectivity"

public_ip=$(sql "settings.ipConfiguration.ipv4Enabled")
expect "the database has no public address" "$public_ip" "False"

# `sslMode` is the field that governs this now; `requireSsl` is the retired v5 spelling the API
# still echoes. Reading the live one means this keeps telling the truth if the legacy field goes.
ssl_mode=$(sql "settings.ipConfiguration.sslMode")
case "$ssl_mode" in
  ENCRYPTED_ONLY | TRUSTED_CLIENT_CERTIFICATE_REQUIRED)
    pass "the database refuses an unencrypted connection (${ssl_mode})"
    ;;
  *)
    fail "the database refuses an unencrypted connection" \
      "sslMode is '${ssl_mode:-unset}', which permits plaintext connections"
    ;;
esac

private_network=$(sql "settings.ipConfiguration.privateNetwork")
if [ -n "$private_network" ]; then
  pass "the database is attached to the private network"
else
  fail "the database is attached to the private network" "no private network is configured"
fi

# --- 11 backups and point-in-time recovery -------------------------------------------------------
echo
echo "Backups and recovery"

backups=$(sql "settings.backupConfiguration.enabled")
expect "automated backups are on" "$backups" "True"

pitr=$(sql "settings.backupConfiguration.pointInTimeRecoveryEnabled")
expect "point-in-time recovery is on" "$pitr" "True"

retention=$(sql "settings.backupConfiguration.transactionLogRetentionDays")
if [ -n "$retention" ] && [ "$retention" -ge 7 ] 2>/dev/null; then
  pass "transaction logs are retained for ${retention} days"
else
  fail "transaction logs are retained for at least 7 days" "found '${retention}'"
fi

# A backup that has never completed is not a backup. This reads the most recent one rather than
# trusting the setting that asked for it.
latest=$(gcloud sql backups list --instance "$INSTANCE" --project "$PROJECT" \
  --sort-by '~windowStartTime' --limit 1 --format 'value(status,windowStartTime)' 2>/dev/null)
case "$latest" in
  SUCCESSFUL*) pass "the most recent backup completed (${latest#SUCCESSFUL})" ;;
  "")          fail "at least one backup has actually completed" "no backups exist yet" ;;
  *)           fail "the most recent backup completed" "its status is '${latest%%	*}'" ;;
esac

ha=$(sql "settings.availabilityType")
expect "the database is regional, not zonal" "$ha" "REGIONAL"

deletion=$(sql "settings.deletionProtectionEnabled")
expect "the instance cannot be deleted by accident" "$deletion" "True"

# --- 11 the WAF -------------------------------------------------------------------------------
echo
echo "WAF"

for service in agfze-backend-lb agfze-frontend-lb; do
  attached=$(gcloud compute backend-services describe "$service" --global --project "$PROJECT" \
    --format 'value(securityPolicy)' 2>/dev/null)
  if [ -n "$attached" ]; then
    pass "${service} sits behind ${attached##*/}"
  else
    fail "${service} sits behind the WAF" "no security policy is attached"
  fi
done

# --- 11 the probes ---------------------------------------------------------------------------
echo
echo "Health probes"

for service in "$BACKEND" "$FRONTEND"; do
  startup=$(run "template.containers[0].startupProbe.httpGet.path" "$service")
  liveness=$(run "template.containers[0].livenessProbe.httpGet.path" "$service")
  if [ -n "$startup" ] && [ -n "$liveness" ]; then
    pass "${service} has both probes wired (${startup}, ${liveness})"
  else
    fail "${service} has both probes wired" "startup='${startup}' liveness='${liveness}'"
  fi
done

readiness=$(run "template.containers[0].startupProbe.httpGet.path" "$BACKEND")
expect "the API's startup probe is the one that checks the database" "$readiness" "/health/ready"

# --- 11 the scheduled sweeps ----------------------------------------------------------------
echo
echo "Scheduled sweeps"

min_instances=$(run "template.scaling.minInstanceCount" "$BACKEND")
if [ -n "$min_instances" ] && [ "$min_instances" -ge 1 ] 2>/dev/null; then
  pass "the API keeps ${min_instances} instance(s) warm, so the sweeps genuinely run"
else
  fail "the API keeps at least one instance warm" \
    "min instances is '${min_instances}' - scaling to zero means the integration retry, the daily report and the monthly report never run"
fi

cpu_idle=$(run "template.containers[0].resources.cpuIdle" "$BACKEND")
expect "the API keeps CPU between requests, which the sweeps need" "$cpu_idle" "False"

# The sweep says so itself, every time it finds work. Absence over the last hour on a system with
# any traffic at all is the signal that the loop has stopped.
recent=$(gcloud logging read \
  "resource.labels.service_name=\"${BACKEND}\" AND jsonPayload.message=\"integration_worker_started\"" \
  --project "$PROJECT" --freshness=7d --limit 1 --format 'value(timestamp)' 2>/dev/null)
if [ -n "$recent" ]; then
  pass "the integration sweep reported starting (${recent})"
else
  fail "the integration sweep has started in the last 7 days" \
    "no 'integration_worker_started' line - check INTEGRATION_SWEEP_ENABLED and the instance count"
fi

# --- 8.1 secrets ------------------------------------------------------------------------------
echo
echo "Secrets"

for secret in keycloak-oidc-client-secret database-password nextauth-secret \
              storage-signed-url-secret azure-ad-client-secret gemini-api-key \
              keycloak-admin-client-secret vapid-private-key smtp-password sentry-dsn; do
  version=$(gcloud secrets versions list "$secret" --project "$PROJECT" \
    --filter 'state=ENABLED' --limit 1 --format 'value(name)' 2>/dev/null)
  if [ -n "$version" ]; then
    pass "${secret} has an enabled version"
  else
    fail "${secret} has an enabled version" "the secret exists but nothing has been put in it"
  fi
done

# --- 8.2 push delivery --------------------------------------------------------------------------
# The failure this catches is specific and was real: the private half was provisioned while the
# public half was never set on the service at all. The API then reports push as unconfigured and
# the production settings profile refuses to start, so a deployment looks provisioned and is not.
# Both halves, on both services, or push does not work.
echo
echo "Push delivery"

# Read as raw JSON rather than through a resource path: the v1 and v2 representations nest the
# container environment differently, and a path that misses would report a configured key as
# absent - or worse, the reverse.
env_names() {
  gcloud run services describe "$1" --project "$PROJECT" --region "$REGION" \
    --format json 2>/dev/null | grep -Eo '"name": *"[A-Z_]+"' | grep -Eo '[A-Z_]+"$' | tr -d '"'
}

if env_names "$BACKEND" | grep -qx 'VAPID_PUBLIC_KEY'; then
  pass "the API carries a VAPID public key"
else
  fail "the API carries a VAPID public key" \
    "only the private half is wired; the API reports push as unconfigured and refuses to start"
fi

if env_names "$BACKEND" | grep -qx 'VAPID_PRIVATE_KEY'; then
  pass "the API carries a VAPID private key"
else
  fail "the API carries a VAPID private key" \
    "nothing can sign a delivery; check the vapid-private-key secret is mounted on the service"
fi

if env_names "$FRONTEND" | grep -qx 'NEXT_PUBLIC_VAPID_PUBLIC_KEY'; then
  pass "the web app carries the VAPID public key"
else
  fail "the web app carries the VAPID public key" \
    "the bundle cannot call pushManager.subscribe, so no browser can ever take a subscription"
fi

placeholder=$(gcloud secrets versions access latest --secret database-password \
  --project "$PROJECT" 2>/dev/null)
if [ "$placeholder" = "CHANGE-ME-BEFORE-GO-LIVE" ]; then
  fail "the database password has been rotated off its placeholder" \
    "it is still the value Terraform created the secret with"
else
  pass "the database password is not the placeholder"
fi
unset placeholder

# Nothing may be sitting in a plain environment variable. Every credential is a secret reference,
# and this reads the deployed revision back to prove it.
#
# Two names are excluded by name rather than by widening the pattern. A VAPID *public* key is
# published to every browser that subscribes - that is what it is for - so it is configuration
# that happens to end in _KEY, and it has to be a literal because the browser cannot read a
# secret reference. Excluding the two exact names keeps the check as strict as it was for
# everything else, including the private half, which must never appear here.
for service in "$BACKEND" "$FRONTEND"; do
  literals=$(gcloud run services describe "$service" --project "$PROJECT" --region "$REGION" \
    --format json 2>/dev/null \
    | grep -Eo '"name": *"[A-Z_]*(SECRET|PASSWORD|_KEY|TOKEN)[A-Z_]*"[^}]*"value":' \
    | grep -Ev '"(NEXT_PUBLIC_)?VAPID_PUBLIC_KEY"' | wc -l)
  if [ "$literals" -eq 0 ]; then
    pass "${service} holds no credential as a literal environment value"
  else
    fail "${service} holds no credential as a literal environment value" \
      "${literals} credential-shaped variable(s) carry a value rather than a secret reference"
  fi
done

# --- summary -----------------------------------------------------------------------------------
echo
if [ "$failures" -eq 0 ]; then
  printf '\033[32m%s of %s checks passed.\033[0m This estate matches what Step 11 promised.\n\n' \
    "$checks" "$checks"
  exit 0
fi

printf '\033[31m%s of %s checks failed.\033[0m Do not sign this off until they pass.\n\n' \
  "$failures" "$checks"
exit 1
