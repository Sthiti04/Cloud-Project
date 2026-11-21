variable "region" {
  type    = string
  default = "ap-south-1"
}
variable "project" {
  type    = string
  default = "s23-demo"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,19}$", var.project))
    error_message = "Use 3-20 lowercase letters, numbers, and hyphens."
  }
}
variable "admin_cidr" {
  type        = string
  description = "Your current public IPv4 /32; restrict the EKS control-plane endpoint."
  validation {
    condition     = can(cidrhost(var.admin_cidr, 0)) && endswith(var.admin_cidr, "/32")
    error_message = "Use your current public IPv4 address followed by /32, not 0.0.0.0/0."
  }
}
variable "admin_principal_arn" {
  type        = string
  description = "IAM user or IAM role ARN, never an STS assumed-role session ARN."
  validation {
    condition     = can(regex("^arn:aws:iam::[0-9]{12}:(user|role)/", var.admin_principal_arn))
    error_message = "Provide an IAM user/role ARN. See the preflight guide for SSO/assumed roles."
  }
}
variable "allow_paid_resources" {
  type    = bool
  default = false
}
variable "allow_delete_demo_data" {
  type        = bool
  default     = false
  description = "Allow Terraform to empty the project's synthetic-data S3 bucket during destroy."
}
variable "enable_runtime" {
  type        = bool
  default     = false
  description = "Second apply: create Lambda and EMR only after building artifacts."
}
variable "lambda_image_uri" {
  type    = string
  default = ""
}
variable "fail_first_delivery" {
  type    = bool
  default = false
}
variable "eks_version" {
  type    = string
  default = "1.35"
}
