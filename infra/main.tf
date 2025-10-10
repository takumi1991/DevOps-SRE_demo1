terraform {
  required_version = ">= 1.6.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.40"
    }
  }
}

provider "google" {
  project     = var.project_id
  region      = var.region
  credentials = var.google_credentials_json
}

# 主要API（既に有効でもOK：IaCで明示）
resource "google_project_service" "services" {
  for_each = toset([
    "container.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
    "secretmanager.googleapis.com",
    "serviceusage.googleapis.com"
  ])
  project = var.project_id
  service = each.key
  disable_on_destroy = false
}

# Artifact Registry (Docker)
resource "google_artifact_registry_repository" "repo" {
  location      = var.region
  repository_id = "demo-repo"
  description   = "Demo Docker repository"
  format        = "DOCKER"
  depends_on    = [google_project_service.services]
}

# GKE Autopilot クラスタ
resource "google_container_cluster" "autopilot" {
  name              = "gke-autopilot-demo"
  location          = var.region
  enable_autopilot  = true
  release_channel { channel = "REGULAR" }
  deletion_protection = false
  depends_on        = [google_project_service.services]
}

# 参考：必要になったら後で追加（Cloud Armor / Monitoring Alert など）
# - google_compute_security_policy
# - google_monitoring_notification_channel
# - google_monitoring_alert_policy
