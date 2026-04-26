variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Prefix for all resource names"
  type        = string
  default     = "aria"
}

variable "aws_account_id" {
  description = "Your AWS account ID"
  type        = string
}

variable "vector_index_name" {
  description = "S3 Vectors index name"
  type        = string
  default     = "research-briefs"
}

variable "langsmith_project" {
  description = "LangSmith project name"
  type        = string
  default     = "aria-production"
}

variable "researcher_url" {
  description = "Aria Researcher App Runner service URL"
  type        = string
  default     = ""
}