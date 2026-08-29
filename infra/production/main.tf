/**
 * The deployed shape of this platform: two containers, one managed database, one secrets store,
 * one WAF, and the schedules that keep the sweeps running.
 *
 * Written as Terraform rather than as a runbook because every claim this step makes about
 * production - encryption at rest, private-only connectivity, point-in-time recovery, a WAF in
 * front of both services - is a claim about a setting somebody has to have actually set. A
 * document saying "enable backups" is not a backup. `verify-production.sh` beside it reads the same
 * settings back out of the live project afterwards, because Terraform proves what was applied and
 * not what is true now.
 *
 * Target: Google Cloud. Nothing in the application is tied to it - both services are ordinary
 * containers and the database is ordinary PostgreSQL - but the infrastructure has to be written
 * against something real to be checkable, and this is what it is deployed on.
 */

terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
  backend "gcs" {
    # State holds resource identifiers and configuration, never secret values - every credential
    # below is a Secret Manager reference rather than a literal. The bucket is still versioned and
    # access-controlled, because state is a map of the estate.
    prefix = "agfze/production"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  labels = {
    application = "agfze-command-centre"
    environment = "production"
    managed_by  = "terraform"
  }
}

# --- private networking ---------------------------------------------------------------------
#
# The database is reachable over private connectivity and nothing else. There is no public IP to
# firewall off, which is stronger than a firewall: an address that does not exist cannot be
# reached by a rule somebody forgot.

resource "google_compute_network" "core" {
  name                    = "agfze-core"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "services" {
  name                     = "agfze-services"
  network                  = google_compute_network.core.id
  ip_cidr_range            = "10.20.0.0/24"
  region                   = var.region
  private_ip_google_access = true
}

# The range Cloud SQL's private instance is allocated inside.
resource "google_compute_global_address" "private_services" {
  name          = "agfze-private-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.core.id
}

resource "google_service_networking_connection" "private_services" {
  network                 = google_compute_network.core.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]
}

# How the two Cloud Run services reach that private range.
resource "google_vpc_access_connector" "run" {
  name          = "agfze-run"
  region        = var.region
  subnet { name = google_compute_subnetwork.services.name }
  min_instances = 2
  max_instances = 4
}

# --- the rate-limit counter store ----------------------------------------------------------------
#
# Cloud Run scales to more than one instance, and in-process rate-limit counters do not survive
# that: each instance counts its own share, so a configured "5 bulk approvals per minute" quietly
# becomes five per minute *per instance*. The limits that matter here guard the approval and bulk-
# approval paths, which is precisely where a multiplied allowance would be worth having.
#
# Sized at the floor deliberately. This holds short-lived integer counters keyed by user and route
# and nothing else - no sessions, no cache, no queue - so the smallest instance is not a saving to
# revisit later, it is the correct size. `BASIC` for the same reason: losing the counters costs
# every in-flight window a reset, which is a moment of over-permissiveness rather than a data loss,
# and does not justify a standby replica.

resource "google_redis_instance" "rate_limits" {
  name           = "agfze-rate-limits"
  tier           = "BASIC"
  memory_size_gb = 1
  region         = var.region

  # Private connectivity only, the same posture the database holds: there is no public address to
  # firewall off, which is stronger than a firewall somebody has to remember to write.
  connect_mode            = "PRIVATE_SERVICE_ACCESS"
  authorized_network      = google_compute_network.core.id
  auth_enabled            = true
  transit_encryption_mode = "SERVER_AUTHENTICATION"

  redis_version = "REDIS_7_0"

  labels = {
    application = "agfze-command-centre"
    environment = "production"
    managed_by  = "terraform"
  }

  depends_on = [google_service_networking_connection.private_services]
}

# --- the database ------------------------------------------------------------------------------

resource "google_sql_database_instance" "primary" {
  name                = "agfze-primary"
  database_version    = "POSTGRES_15"
  region              = var.region
  deletion_protection = true

  settings {
    tier              = var.database_tier
    availability_type = "REGIONAL"
    disk_type         = "PD_SSD"
    disk_size         = 50
    disk_autoresize   = true
    user_labels       = local.labels

    ip_configuration {
      # No public address at all. This is the setting Section 8.5 asks to be verified rather than
      # assumed, and `verify-production.sh` reads it back.
      ipv4_enabled                                  = false
      private_network                               = google_compute_network.core.id
      enable_private_path_for_google_cloud_services = true
      require_ssl                                   = true
    }

    backup_configuration {
      enabled = true
      # Point-in-time recovery. Without this a backup restores yesterday; with it, any moment in
      # the retention window - which is what "we can undo the bad Tuesday afternoon" requires.
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7
      start_time                     = "18:00" # 22:00 Gulf time, after the desk has gone home.
      location                       = var.region

      backup_retention_settings {
        retained_backups = 30
        retention_unit   = "COUNT"
      }
    }

    maintenance_window {
      day          = 7 # Sunday
      hour         = 19
      update_track = "stable"
    }

    insights_config {
      query_insights_enabled  = true
      record_application_tags = false
      record_client_address   = false
    }
  }

  # Encryption at rest is on by every Cloud SQL instance by default with a Google-managed key.
  # This platform holds commercial contracts and counterparty terms, so it uses a key AGFZE owns
  # and can revoke - which is the difference between "encrypted" and "encrypted with a key we
  # control". Naming it here is also what makes it checkable rather than assumed.
  encryption_key_name = google_kms_crypto_key.database.id

  depends_on = [google_service_networking_connection.private_services]
}

resource "google_sql_database" "application" {
  name     = "agfze"
  instance = google_sql_database_instance.primary.name
}

resource "google_sql_user" "application" {
  name     = "agfze_app"
  instance = google_sql_database_instance.primary.name
  password = google_secret_manager_secret_version.database_password.secret_data
}

# --- customer-managed keys ------------------------------------------------------------------

resource "google_kms_key_ring" "core" {
  name     = "agfze-core"
  location = var.region
}

resource "google_kms_crypto_key" "database" {
  name            = "agfze-database"
  key_ring        = google_kms_key_ring.core.id
  rotation_period = "7776000s" # 90 days
  lifecycle { prevent_destroy = true }
}

resource "google_kms_crypto_key" "storage" {
  name            = "agfze-storage"
  key_ring        = google_kms_key_ring.core.id
  rotation_period = "7776000s"
  lifecycle { prevent_destroy = true }
}

# --- document storage --------------------------------------------------------------------------
#
# Every source document, page image and generated draft. Encrypted with the same customer-managed
# key, versioned so an overwrite is recoverable, and with no public access of any kind: files are
# served only through the application's own short-lived signed URLs.

resource "google_storage_bucket" "documents" {
  name                        = "${var.project_id}-agfze-documents"
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = local.labels

  versioning { enabled = true }

  encryption {
    default_kms_key_name = google_kms_crypto_key.storage.id
  }

  lifecycle_rule {
    condition { num_newer_versions = 5 }
    action { type = "Delete" }
  }
}

# --- secrets -------------------------------------------------------------------------------------
#
# Every credential in the Section 8.1 table, one secret each, none of them ever in an environment
# file, a container image or this repository. The values are set out of band - `terraform apply`
# creates the secret, a person or a pipeline adds the version - which is why only the containers
# are declared here and not one literal.

locals {
  secret_ids = [
    "keycloak-oidc-client-secret",   # Step 1  human sign-in
    "database-password",             # Step 1  Postgres
    "nextauth-secret",               # Step 1  session signing
    "storage-signed-url-secret",     # Step 1  document link signing
    "sentry-dsn",                    # Step 1  error tracking
    "azure-ad-client-secret",        # Step 2  mailbox intake, Step 7 tracker
    "gemini-api-key",                # Step 2  every AI call
    "sap-api-password",              # Step 7  SAP posting, optional
    "sap-api-key",                   # Step 7  SAP posting, optional
    "dms-api-password",              # Step 7  DMS upload, optional
    "dms-api-key",                   # Step 7  DMS upload, optional
    "keycloak-admin-client-secret",  # Step 9  role override
    "vapid-private-key",             # Step 10 push signing
    "smtp-password",                 # Step 10 email delivery
  ]
}

resource "google_secret_manager_secret" "credentials" {
  for_each  = toset(local.secret_ids)
  secret_id = each.value
  labels    = local.labels

  replication {
    user_managed {
      replicas {
        location = var.region
        customer_managed_encryption {
          kms_key_name = google_kms_crypto_key.storage.id
        }
      }
    }
  }
}

# One placeholder version, so a first `apply` against an empty project has something to create the
# database user from. It is rotated out of band immediately afterwards, and `ignore_changes` is
# what keeps a later `apply` from putting the placeholder back over the real value.
#
# `verify-production.sh` reads this secret back and fails the go-live sign-off while it still holds
# the placeholder, which is the only reason it is safe to have one at all.
resource "google_secret_manager_secret_version" "database_password" {
  secret      = google_secret_manager_secret.credentials["database-password"].id
  secret_data = "CHANGE-ME-BEFORE-GO-LIVE"
  lifecycle { ignore_changes = [secret_data] }
}

# --- service identities -------------------------------------------------------------------------
#
# One per service, each holding only what that service actually needs. The frontend never reaches
# the database or a document, so it is not granted either.

resource "google_service_account" "backend" {
  account_id   = "agfze-backend"
  display_name = "AGFZE Command Centre - API"
}

resource "google_service_account" "frontend" {
  account_id   = "agfze-frontend"
  display_name = "AGFZE Command Centre - web"
}

resource "google_secret_manager_secret_iam_member" "backend_secrets" {
  for_each  = toset([for id in local.secret_ids : id if id != "nextauth-secret"])
  secret_id = google_secret_manager_secret.credentials[each.value].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backend.email}"
}

resource "google_secret_manager_secret_iam_member" "frontend_secrets" {
  # Two, and only two: the session signing key and the OIDC client secret. The frontend has no
  # business holding a Graph credential or a Gemini key, and does not.
  for_each  = toset(["nextauth-secret", "keycloak-oidc-client-secret"])
  secret_id = google_secret_manager_secret.credentials[each.value].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.frontend.email}"
}

resource "google_storage_bucket_iam_member" "backend_documents" {
  bucket = google_storage_bucket.documents.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.backend.email}"
}

resource "google_project_iam_member" "backend_sql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

# --- the graph projection --------------------------------------------------------------------
#
# A derived, rebuildable read model for traceability questions that are expensive as recursive SQL.
# Gated behind `enable_graph_projection`, which is false: standing up a graph database is a real
# ongoing commitment and belongs to AGFZE rather than to a default. With it off, the application
# reports the trace as unavailable and nothing else changes - no other feature reads this store.
#
# Self-hosted Community on a small instance rather than AuraDB, for one reason: AuraDB is a
# separate vendor relationship and a separate data-processing agreement, and this holds identifiers
# drawn from trade records. Keeping it inside the existing VPC keeps it inside the estate AGFZE has
# already reviewed. Swap it for AuraDB by replacing this block and the NEO4J_URI it feeds.

resource "google_compute_instance" "graph" {
  count = var.enable_graph_projection ? 1 : 0

  name         = "agfze-graph"
  machine_type = var.graph_machine_type
  zone         = "${var.region}-a"

  boot_disk {
    initialize_params {
      image = "projects/cos-cloud/global/images/family/cos-stable"
      size  = 20
      type  = "pd-ssd"
    }
  }

  # No public address at all. The projection is reachable from the VPC connector the two Cloud Run
  # services already use, and from nowhere else - an address that does not exist cannot be reached
  # by a firewall rule somebody forgot to write.
  network_interface {
    network    = google_compute_network.core.id
    subnetwork = google_compute_subnetwork.services.id
  }

  service_account {
    email  = google_service_account.backend.email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }

  labels = {
    application = "agfze-command-centre"
    environment = "production"
    managed_by  = "terraform"
    component   = "graph-projection"
  }

  # Recreating this instance loses nothing that matters: the projection is derived, and
  # `python -m scripts.rebuild_graph` rebuilds it from the relational store.
  allow_stopping_for_update = true
}

resource "google_compute_firewall" "graph_bolt" {
  count = var.enable_graph_projection ? 1 : 0

  name    = "agfze-graph-bolt"
  network = google_compute_network.core.name

  allow {
    protocol = "tcp"
    ports    = ["7687"]
  }

  # The services subnet only. Not the whole VPC, and never the internet.
  source_ranges = [google_compute_subnetwork.services.ip_cidr_range]
  target_tags   = ["agfze-graph"]
}
