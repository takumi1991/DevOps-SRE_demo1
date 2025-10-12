terraform {
  required_version = ">= 1.6.0"
  required_providers {
    google = { source = "hashicorp/google", version = "~> 5.40" }
  }
}

provider "google" {
  project     = var.project_id
  region      = var.region
  credentials = var.google_credentials_json
}

# 必要API（GKEは除外）
resource "google_project_service" "services" {
  for_each = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
    "iam.googleapis.com",
    "serviceusage.googleapis.com"
  ])
  project = var.project_id
  service = each.key
  disable_on_destroy = false
}

# Artifact Registry（既存リポを参照に変更）
# いまの resource ブロックを削除して、↓の data ブロックにする
data "google_artifact_registry_repository" "repo" {
  location      = var.region
  repository_id = "demo-repo"
}

# まずは公開のサンプルイメージでデモ（自前ビルド不要）
# 後で自作イメージに差し替え可：REGION-docker.pkg.dev/PROJECT/demo-repo/hello:latest
resource "google_cloud_run_v2_service" "hello" {
  name     = "hello-demo"
  location = var.region

  template {
    # Cloud Run 推奨の公開イメージ（8080で応答）
    containers {
      image = "us-docker.pkg.dev/cloudrun/container/hello:latest"
      ports { container_port = 8080 }
    }
  }

  depends_on = [google_project_service.services]
}

# 認証なしでの呼び出しを許可（URL直アクセス可）
resource "google_cloud_run_v2_service_iam_member" "invoker_all" {
  name     = google_cloud_run_v2_service.hello.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}
