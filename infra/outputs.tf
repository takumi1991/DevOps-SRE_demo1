output "project_id"   { value = var.project_id }
output "region"       { value = var.region }
output "cluster_name" { value = google_container_cluster.autopilot.name }
output "repo_url"     {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.repository_id}"
}
