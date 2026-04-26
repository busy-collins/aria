variable "aws_region" {
  description = "us-east-1"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "aria"
  type        = string
  default     = "aria"
}

variable "aws_account_id" {
  description = "975022060655"
  type        = string
}

variable "openai_api_key" {
  description = "OpenAI API key for agent tracing"
  type        = string
  sensitive   = true
}

variable "aria_api_endpoint" {
  description = "Aria ingest API endpoint from module 3"
  type        = string
}

variable "aria_api_key" {
  description = "Aria ingest API key from module 3"
  type        = string
  sensitive   = true
}

variable "scheduler_enabled" {
  description = "Enable EventBridge scheduler for automated research"
  type        = bool
  default     = false
}