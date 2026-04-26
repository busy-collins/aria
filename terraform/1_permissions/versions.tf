# versions.tf tells Terraform:
#   1. Which version of Terraform itself is required
#   2. Which cloud providers to download
#   3. Which version of each provider

terraform {
  required_version = ">= 1.5"           # minimum Terraform version

  required_providers {
    aws = {
      source  = "hashicorp/aws"          # download from official registry
      version = "~> 5.0"                 # any 5.x version — NOT 6.x
    }
  }

  # State file lives locally in this directory
  # This means each module tracks its own infrastructure
  # independently — destroying module 4 won't touch module 2
  backend "local" {}
}

provider "aws" {
  region = var.aws_region                # uses variable defined in variables.tf
}