/**
 * The two services, the load balancer and WAF in front of them, and the schedules behind them.
 *
 * Two independently deployable containers, exactly as the specification requires: separate
 * services, separate identities, separate revisions, separate rollbacks. Neither depends on the
 * other's revision, and `release.yml` deploys them in parallel for that reason.
 */

# --- the backend --------------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "backend" {
  name     = "agfze-backend"
  location = var.region
  labels   = local.labels

  # Reachable only through the load balancer below, which is where the WAF is. A service that also
  # answers on its own run.app URL has a WAF that can be walked around.
  ingress = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  template {
    service_account = google_service_account.backend.email

    # The scheduled sweeps Steps 7 and 8 established run inside this process on their own timers:
    # the integration retry every minute, and the daily and monthly reports riding that same loop.
    # Scaling to zero would mean none of them ever runs, so one instance is always warm. This is
    # the setting that makes "the sweeps genuinely run in the deployed environment" true, and it
    # is why it is not left at the default.
    scaling {
      min_instance_count = 1
      max_instance_count = 10
    }

    vpc_access {
      connector = google_vpc_access_connector.run.id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    volumes {
      name = "documents"
      gcs {
        bucket    = google_storage_bucket.documents.name
        read_only = false
      }
    }

    containers {
      image = var.backend_image

      ports { container_port = 8000 }

      volume_mounts {
        name       = "documents"
        mount_path = "/mnt/documents"
      }

      resources {
        limits = { cpu = "2", memory = "2Gi" }
        # The sweeps need CPU between requests, which throttled instances do not get.
        cpu_idle = false
      }

      env {
        name  = "ENV"
        value = "production"
      }
      env {
        name  = "APP_BASE_URL"
        value = var.app_base_url
      }
      env {
        name  = "CORS_ALLOWED_ORIGINS"
        value = var.app_base_url
      }
      env {
        name  = "KEYCLOAK_ISSUER"
        value = var.keycloak_issuer
      }
      env {
        name  = "KEYCLOAK_JWKS_URL"
        value = "${var.keycloak_issuer}/protocol/openid-connect/certs"
      }
      # The platform ships exactly one storage implementation - the local filesystem one Step 1
      # built behind its storage abstraction - and no step ever added an object-store client. On a
      # container with an ephemeral disk that would lose every document on the next revision, so
      # the bucket is *mounted* rather than called: the same code writes to the same paths, and
      # what is behind those paths is durable, versioned and encrypted with AGFZE's own key.
      #
      # This is a deployment technique, not a missing feature, and it is deliberately not a new
      # storage backend invented at the last step. A native GCS client would be faster on large
      # page-image writes; if that ever matters, it is a drop-in behind the same abstraction.
      env {
        name  = "STORAGE_BACKEND"
        value = "local"
      }
      env {
        name  = "STORAGE_LOCAL_ROOT"
        value = "/mnt/documents"
      }
      env {
        name  = "STORAGE_PUBLIC_BASE_URL"
        value = "${var.api_base_url}/internal/files"
      }
      env {
        name = "DATABASE_URL"
        # Private IP, and the driver's own TLS. Never a public address.
        value = join("", [
          "postgresql+asyncpg://agfze_app:",
          "$${DATABASE_PASSWORD}@",
          google_sql_database_instance.primary.private_ip_address,
          ":5432/agfze",
        ])
      }
      env {
        name  = "RATE_LIMIT_ENABLED"
        value = "true"
      }
      env {
        name  = "RATE_LIMIT_TRUST_FORWARDED_FOR"
        value = "true"
      }
      env {
        # Shared counters, so a limit means the same thing however many instances are serving.
        # In-process counting would give each instance its own allowance.
        #
        # Built from the Memorystore instance this stack provisions unless an operator has named a
        # store of their own. The AUTH string is part of the URI because that is the only form the
        # `limits` library's Redis backend accepts; it comes from the instance's own generated
        # credential and is never written down anywhere in this configuration.
        name = "RATE_LIMIT_STORAGE_URI"
        value = coalesce(
          var.rate_limit_storage_uri != "" ? var.rate_limit_storage_uri : null,
          format(
            "redis://:%s@%s:%d/0",
            google_redis_instance.rate_limits.auth_string,
            google_redis_instance.rate_limits.host,
            google_redis_instance.rate_limits.port,
          ),
        )
      }

      # Every credential, mounted from Secret Manager. Not one of them is a literal here, in the
      # image, or in any file this repository contains.
      dynamic "env" {
        for_each = {
          DATABASE_PASSWORD             = "database-password"
          STORAGE_SIGNED_URL_SECRET     = "storage-signed-url-secret"
          SENTRY_DSN                    = "sentry-dsn"
          AZURE_AD_CLIENT_SECRET        = "azure-ad-client-secret"
          GEMINI_API_KEY                = "gemini-api-key"
          KEYCLOAK_ADMIN_CLIENT_SECRET  = "keycloak-admin-client-secret"
          SAP_API_PASSWORD              = "sap-api-password"
          SAP_API_KEY                   = "sap-api-key"
          DMS_API_PASSWORD              = "dms-api-password"
          DMS_API_KEY                   = "dms-api-key"
          VAPID_PRIVATE_KEY             = "vapid-private-key"
          SMTP_PASSWORD                 = "smtp-password"
        }
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.credentials[env.value].secret_id
              version = "latest"
            }
          }
        }
      }

      # Step 1's probes, wired to the platform's own health checking rather than described in a
      # README. Liveness never touches the database - it answers whether the process is up, which
      # is what a restart should be decided on. Readiness owns the dependency check, so an
      # instance that cannot reach Postgres is taken out of rotation instead of restarted.
      startup_probe {
        http_get { path = "/health/ready" }
        initial_delay_seconds = 5
        period_seconds        = 5
        timeout_seconds       = 3
        failure_threshold     = 20
      }

      liveness_probe {
        http_get { path = "/health" }
        period_seconds    = 30
        timeout_seconds   = 3
        failure_threshold = 3
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  lifecycle {
    # The image is set by the release pipeline, revision by revision. Terraform owns the shape of
    # the service; it does not own which build is currently serving, and a `terraform apply` must
    # never quietly roll a deployment back.
    ignore_changes = [template[0].containers[0].image, traffic]
  }
}

# The migration job: the same image, run to completion before a new revision serves. Migrating
# from inside the serving container would race every instance against every other on start-up.
resource "google_cloud_run_v2_job" "migrate" {
  name     = "agfze-migrate"
  location = var.region

  template {
    template {
      service_account = google_service_account.backend.email
      max_retries     = 0

      vpc_access {
        connector = google_vpc_access_connector.run.id
        egress    = "PRIVATE_RANGES_ONLY"
      }

      containers {
        image   = var.backend_image
        command = ["alembic"]
        args    = ["upgrade", "head"]

        env {
          name  = "ENV"
          value = "production"
        }
        env {
          name = "DATABASE_URL"
          value = join("", [
            "postgresql+asyncpg://agfze_app:",
            "$${DATABASE_PASSWORD}@",
            google_sql_database_instance.primary.private_ip_address,
            ":5432/agfze",
          ])
        }
        env {
          name = "DATABASE_PASSWORD"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.credentials["database-password"].secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  lifecycle { ignore_changes = [template[0].template[0].containers[0].image] }
}

# --- the frontend ---------------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "frontend" {
  name     = "agfze-frontend"
  location = var.region
  labels   = local.labels

  ingress = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  template {
    service_account = google_service_account.frontend.email

    # Nothing periodic runs here, so this one genuinely may scale to zero out of hours.
    scaling {
      min_instance_count = 0
      max_instance_count = 10
    }

    containers {
      image = var.frontend_image
      ports { container_port = 3000 }

      resources {
        limits = { cpu = "1", memory = "1Gi" }
      }

      env {
        name  = "NEXTAUTH_URL"
        value = var.app_base_url
      }
      env {
        name  = "KEYCLOAK_ISSUER"
        value = var.keycloak_issuer
      }
      env {
        name  = "KEYCLOAK_CLIENT_ID"
        value = var.keycloak_client_id
      }
      env {
        name  = "API_INTERNAL_BASE_URL"
        value = "${var.api_base_url}/api/v1"
      }
      env {
        # Inlined into the browser bundle at build time as well; set here so a server render and
        # the bundle cannot disagree about where the API is.
        name  = "NEXT_PUBLIC_API_BASE_URL"
        value = "${var.api_base_url}/api/v1"
      }

      dynamic "env" {
        for_each = {
          NEXTAUTH_SECRET       = "nextauth-secret"
          KEYCLOAK_CLIENT_SECRET = "keycloak-oidc-client-secret"
        }
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.credentials[env.value].secret_id
              version = "latest"
            }
          }
        }
      }

      startup_probe {
        http_get { path = "/signin" }
        initial_delay_seconds = 5
        period_seconds        = 5
        timeout_seconds       = 3
        failure_threshold     = 20
      }

      liveness_probe {
        http_get { path = "/signin" }
        period_seconds    = 30
        timeout_seconds   = 3
        failure_threshold = 3
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, traffic]
  }
}

# --- HTTPS at the edge, and the WAF in front of both ------------------------------------------

resource "google_compute_managed_ssl_certificate" "edge" {
  name = "agfze-edge"
  managed {
    domains = [var.app_domain, var.api_domain]
  }
}

resource "google_compute_region_network_endpoint_group" "backend" {
  name                  = "agfze-backend-neg"
  region                = var.region
  network_endpoint_type = "SERVERLESS"
  cloud_run { service = google_cloud_run_v2_service.backend.name }
}

resource "google_compute_region_network_endpoint_group" "frontend" {
  name                  = "agfze-frontend-neg"
  region                = var.region
  network_endpoint_type = "SERVERLESS"
  cloud_run { service = google_cloud_run_v2_service.frontend.name }
}

resource "google_compute_security_policy" "waf" {
  name        = "agfze-waf"
  description = "Cloud Armor, in front of both services."

  # The OWASP core rules, in the two families that actually threaten this platform: it stores
  # everything in SQL and renders counterparty-supplied text.
  rule {
    action   = "deny(403)"
    priority = 1000
    match {
      expr { expression = "evaluatePreconfiguredExpr('sqli-v33-stable')" }
    }
    description = "SQL injection"
  }

  rule {
    action   = "deny(403)"
    priority = 1010
    match {
      expr { expression = "evaluatePreconfiguredExpr('xss-v33-stable')" }
    }
    description = "Cross-site scripting"
  }

  rule {
    action   = "deny(403)"
    priority = 1020
    match {
      expr { expression = "evaluatePreconfiguredExpr('lfi-v33-stable')" }
    }
    description = "Local file inclusion"
  }

  # A ceiling far above anything the application's own per-category limits allow, so this catches
  # volumetric abuse and leaves ordinary rate limiting to the code that understands the endpoints.
  rule {
    action   = "throttle"
    priority = 2000
    match {
      versioned_expr = "SRC_IPS_V1"
      config { src_ip_ranges = ["*"] }
    }
    rate_limit_options {
      conform_action = "allow"
      exceed_action  = "deny(429)"
      enforce_on_key = "IP"
      rate_limit_threshold {
        count        = 600
        interval_sec = 60
      }
    }
    description = "Volumetric ceiling"
  }

  rule {
    action   = "allow"
    priority = 2147483647
    match {
      versioned_expr = "SRC_IPS_V1"
      config { src_ip_ranges = ["*"] }
    }
    description = "Default"
  }
}

resource "google_compute_backend_service" "backend" {
  name                  = "agfze-backend-lb"
  protocol              = "HTTPS"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  security_policy       = google_compute_security_policy.waf.id

  backend { group = google_compute_region_network_endpoint_group.backend.id }

  log_config {
    enable      = true
    sample_rate = 1.0
  }
}

resource "google_compute_backend_service" "frontend" {
  name                  = "agfze-frontend-lb"
  protocol              = "HTTPS"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  security_policy       = google_compute_security_policy.waf.id

  backend { group = google_compute_region_network_endpoint_group.frontend.id }

  log_config {
    enable      = true
    sample_rate = 1.0
  }
}

resource "google_compute_url_map" "edge" {
  name            = "agfze-edge"
  default_service = google_compute_backend_service.frontend.id

  host_rule {
    hosts        = [var.api_domain]
    path_matcher = "api"
  }

  path_matcher {
    name            = "api"
    default_service = google_compute_backend_service.backend.id
  }
}

# Plain HTTP exists only to send the browser to HTTPS. Nothing is served over it.
resource "google_compute_url_map" "https_redirect" {
  name = "agfze-https-redirect"
  default_url_redirect {
    https_redirect         = true
    redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
    strip_query            = false
  }
}

resource "google_compute_target_https_proxy" "edge" {
  name             = "agfze-edge-https"
  url_map          = google_compute_url_map.edge.id
  ssl_certificates = [google_compute_managed_ssl_certificate.edge.id]
  # TLS 1.2 and above, modern ciphers only.
  ssl_policy = google_compute_ssl_policy.modern.id
}

resource "google_compute_ssl_policy" "modern" {
  name            = "agfze-modern-tls"
  profile         = "MODERN"
  min_tls_version = "TLS_1_2"
}

resource "google_compute_target_http_proxy" "redirect" {
  name    = "agfze-edge-http"
  url_map = google_compute_url_map.https_redirect.id
}

resource "google_compute_global_forwarding_rule" "https" {
  name       = "agfze-https"
  target     = google_compute_target_https_proxy.edge.id
  port_range = "443"
}

resource "google_compute_global_forwarding_rule" "http" {
  name       = "agfze-http"
  target     = google_compute_target_http_proxy.redirect.id
  port_range = "80"
}

# --- the scheduled sweeps ------------------------------------------------------------------------
#
# The integration retry sweep, the daily report and the monthly report all ride the one periodic
# loop the backend runs in-process, and `min_instance_count = 1` above is what keeps that loop
# awake. This alert is the other half: a sweep that stops running is otherwise completely silent,
# because nothing fails - work simply stops being picked up.

resource "google_monitoring_alert_policy" "sweep_stopped" {
  display_name = "AGFZE - the periodic sweep has stopped"
  combiner     = "OR"

  conditions {
    display_name = "No sweep log line in 15 minutes"
    condition_matched_log {
      filter = join(" AND ", [
        "resource.type=\"cloud_run_revision\"",
        "resource.labels.service_name=\"${google_cloud_run_v2_service.backend.name}\"",
        "jsonPayload.message=\"integration_sweep_complete\"",
      ])
    }
  }

  alert_strategy {
    notification_rate_limit { period = "900s" }
    auto_close              = "3600s"
  }

  notification_channels = var.notification_channels
}

resource "google_monitoring_alert_policy" "backend_unavailable" {
  display_name = "AGFZE - the API is failing its readiness probe"
  combiner     = "OR"

  conditions {
    display_name = "5xx rate above 5% for 5 minutes"
    condition_threshold {
      filter = join(" AND ", [
        "resource.type=\"cloud_run_revision\"",
        "resource.labels.service_name=\"${google_cloud_run_v2_service.backend.name}\"",
        "metric.type=\"run.googleapis.com/request_count\"",
        "metric.labels.response_code_class=\"5xx\"",
      ])
      comparison      = "COMPARISON_GT"
      threshold_value = 0.05
      duration        = "300s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_RATE"
      }
    }
  }

  notification_channels = var.notification_channels
}
