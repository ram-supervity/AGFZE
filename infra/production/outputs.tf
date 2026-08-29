output "backend_service" {
  value       = google_cloud_run_v2_service.backend.name
  description = "Roll back on its own with: gcloud run services update-traffic <this> --to-revisions <revision>=100"
}

output "frontend_service" {
  value       = google_cloud_run_v2_service.frontend.name
  description = "Rolls back independently of the API; neither needs the other."
}

output "database_instance" {
  value       = google_sql_database_instance.primary.name
  description = "Private IP only, regional, CMEK-encrypted, with point-in-time recovery on."
}

output "database_private_ip" {
  value       = google_sql_database_instance.primary.private_ip_address
  description = "Reachable from the VPC connector and from nowhere else."
  sensitive   = true
}

output "documents_bucket" {
  value       = google_storage_bucket.documents.name
  description = "Public access prevention enforced; served only through signed URLs."
}

output "secret_ids" {
  value       = [for secret in google_secret_manager_secret.credentials : secret.secret_id]
  description = "Every credential in the Section 8.1 table. Values are never held in Terraform."
}

output "waf_policy" {
  value       = google_compute_security_policy.waf.name
  description = "Cloud Armor, applied to both backend services behind one load balancer."
}

output "rate_limit_store_host" {
  description = "Private address of the Memorystore instance holding the rate-limit counters."
  value       = google_redis_instance.rate_limits.host
}

output "rate_limit_store_configured" {
  description = <<-DESC
    Whether the API is counting rate limits in a shared store rather than in each instance's own
    memory. False means a configured limit is multiplied by the number of serving instances.
  DESC
  value       = var.rate_limit_storage_uri == "" || !startswith(var.rate_limit_storage_uri, "memory://")
}

output "graph_projection_enabled" {
  description = <<-DESC
    Whether the traceability projection is provisioned. False is the expected state: it is a
    derived read model and no other feature depends on it.
  DESC
  value       = var.enable_graph_projection
}

output "graph_private_ip" {
  description = "Private address of the graph projection, where it is enabled."
  value = var.enable_graph_projection ? (
    google_compute_instance.graph[0].network_interface[0].network_ip
  ) : null
}
