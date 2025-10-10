terraform {
  required_version = ">= 1.6.0"
  required_providers {
    google = { source = "hashicorp/google", version = "~> 5.40" }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# 必要なAPIを有効化
resource "google_project_service" "services" {
  for_each = toset([
    "container.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
    "secretmanager.googleapis.com",
  ])
  project = var.project_id
  service = each.key
}

# Artifact Registry（Docker）
resource "google_artifact_registry_repository" "repo" {
  location      = var.region
  repository_id = "demo-repo"
  description   = "Demo Docker repo"
  format        = "DOCKER"
}

# GKE Autopilot
resource "google_container_cluster" "autopilot" {
  name     = "gke-autopilot-demo"
  location = var.region
  enable_autopilot = true
  release_channel { channel = "REGULAR" }
  deletion_protection = false
  depends_on = [google_project_service.services]
}

# Slack通知チャネル（Monitoring）※Slack Webhook URLはSecret経由推奨
resource "google_monitoring_notification_channel" "slack" {
  display_name = "Slack Alerts"
  type         = "slack"
  labels = {
    channel_name = "#alerts"
  }
  sensitive_labels {
    auth_token  = var.slack_auth_token   # Slack AppのOAuth Token（受信用）
    webhook_url = var.slack_webhook_url  # Incoming Webhookでも可
  }
}

# 500エラー率の簡易アラート例（実戦では適切なフィルタに調整）
resource "google_monitoring_alert_policy" "http_5xx" {
  display_name = "GKE 5xx Error Rate High"
  combiner     = "OR"
  conditions {
    display_name = "5xx > 1% (5m)"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/5xx_rate\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0.01
      trigger { count = 1 }
      aggregations { alignment_period = "60s" per_series_aligner = "ALIGN_MEAN" }
    }
  }
  notification_channels = [google_monitoring_notification_channel.slack.name]
}
