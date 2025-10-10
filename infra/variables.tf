variable "project_id" { type = string }
variable "region"     { type = string  default = "asia-northeast1" }
variable "slack_auth_token"  { type = string  sensitive = true }
variable "slack_webhook_url" { type = string  sensitive = true }
