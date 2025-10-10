variable "project_id" {
  type = string
  # 例: "devops-sre-demo1"  ← 既にTF CloudのTerraform Variablesで設定済にする
}

variable "region" {
  type    = string
  default = "asia-northeast1"  # 東京。別リージョンなら変更可
}

variable "google_credentials_json" {
  type      = string
  sensitive = true  # TF CloudのTerraform Variablesに「JSON全文」を貼付け済
}
