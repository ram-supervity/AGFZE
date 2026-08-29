variable "project_id" {
  type        = string
  description = "The Google Cloud project this platform is deployed into."
}

variable "region" {
  type        = string
  default     = "me-central1"
  description = "Dubai. The database, both services and the document bucket all live here."
}

variable "database_tier" {
  type        = string
  default     = "db-custom-2-7680"
  description = "Cloud SQL machine type. Regional (high-availability) is set unconditionally."
}

variable "backend_image" {
  type        = string
  description = <<-DESC
    The API image. Set once so the service can be created; from then on the release pipeline owns
    it revision by revision, and Terraform ignores changes to it so an apply cannot roll a
    deployment back by accident.
  DESC
}

variable "frontend_image" {
  type        = string
  description = "The web image, on the same terms as the API image."
}

variable "app_domain" {
  type        = string
  description = "Where staff reach the application, e.g. command-centre.agfze.ae."
}

variable "api_domain" {
  type        = string
  description = "Where the browser reaches the API, e.g. api.command-centre.agfze.ae."
}

variable "app_base_url" {
  type        = string
  description = <<-DESC
    The application's own public origin, absolute. Every email call-to-action is built from this
    rather than from a request header, which is what keeps a forged Host from rewriting the button
    in a message nobody can un-send. The production settings profile refuses to start if it is
    unset or still points at localhost.
  DESC
}

variable "api_base_url" {
  type        = string
  description = "The API's public origin, absolute, without the /api/v1 suffix."
}

variable "keycloak_issuer" {
  type        = string
  description = "The realm URL exactly as it appears in the `iss` claim."
}

variable "keycloak_client_id" {
  type        = string
  default     = "agfze-command-centre"
  description = "The OIDC client staff sign in through. Holds no administrative grant."
}

variable "rate_limit_storage_uri" {
  type        = string
  default     = ""
  description = <<-DESC
    Where the rate-limit counters live. Leave empty - the default - and the stack points the API at
    the Memorystore instance this configuration provisions, which is what makes a configured limit
    mean the same thing however many instances are serving.

    Set it only to override that with a store you manage yourself. Setting it to "memory://" is
    possible and is a deliberate downgrade: counters go back to being per-instance, so a "5 per
    minute" limit becomes five per minute per instance. The API refuses to start in production
    with that value unless RATE_LIMIT_ALLOW_IN_PROCESS is also set, so the downgrade cannot happen
    by accident.
  DESC
}

variable "notification_channels" {
  type        = list(string)
  default     = []
  description = "Monitoring notification channel ids the alert policies fire into."
}

variable "enable_graph_projection" {
  type        = bool
  default     = false
  description = <<-DESC
    Whether to provision the Neo4j instance backing the traceability projection.

    False, and deliberately so. The projection is a derived read model - nothing on the platform
    depends on it, every value it holds is read from PostgreSQL first, and it can be rebuilt from
    scratch at any time - but standing it up is a real, ongoing infrastructure commitment. That is
    AGFZE's decision to make rather than a default to inherit, so the code is complete and the
    resource is off until somebody turns it on.

    The application side needs no change either way: GRAPH_SYNC_ENABLED and the NEO4J_* settings
    are read at runtime, and with no store configured the trace endpoint reports itself unavailable
    rather than failing.
  DESC
}

variable "graph_machine_type" {
  type        = string
  default     = "e2-small"
  description = <<-DESC
    The instance the graph projection runs on, where it is enabled at all. Small on purpose: the
    projection holds identifiers and labels rather than the platform's data, and it answers one
    bounded traversal per transaction workspace view.
  DESC
}

variable "vapid_public_key" {
  type        = string
  description = <<-DESC
    The Web Push application server key, PUBLIC half only, in the raw unpadded URL-safe base64
    form `make vapid-keys` prints.

    It is a variable rather than a Secret Manager entry because it is public by the Web Push
    standard's own design: the browser is handed it to bind a subscription with, the API serves
    it from `/notifications/vapid-public-key`, and the frontend bundle carries it. Its private
    counterpart is the `vapid-private-key` secret and never leaves Secret Manager.

    There is no default, deliberately. The production settings profile refuses to start without
    it - a deployment whose approvers cannot be pushed to is the exact failure the notification
    work exists to remove - so an unset key must stop `terraform apply`, not surface later as a
    container that will not come up.

    Generate the pair ONCE per environment and keep it. Regenerating invalidates every push
    subscription every browser has ever taken against this deployment, and each of those users
    has to grant permission again.
  DESC

  validation {
    condition     = length(trimspace(var.vapid_public_key)) > 0
    error_message = "vapid_public_key must be set; run `make vapid-keys` and supply the public half."
  }
}

variable "vapid_subject" {
  type        = string
  description = <<-DESC
    The `sub` claim on every signed push delivery: a mailto: or https: URL a push service operator
    can reach a human on if this deployment starts misbehaving. Required by the VAPID spec.
  DESC
  default     = "mailto:command-centre@agfze.ae"

  validation {
    condition     = can(regex("^(mailto:|https://)", var.vapid_subject))
    error_message = "vapid_subject must be a mailto: address or an https: URL, as VAPID requires."
  }
}
