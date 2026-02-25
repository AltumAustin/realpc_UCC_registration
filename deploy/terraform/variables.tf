variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-west-2"
}

variable "vpc_id" {
  description = "ID of the existing VPC"
  type        = string
}

variable "subnet_id" {
  description = "ID of the subnet to place the EC2 instance in"
  type        = string
}

variable "ssh_key_name" {
  description = "Name of the EC2 key pair for SSH access"
  type        = string
}

variable "operator_ip" {
  description = "Your IP address for SSH access (CIDR notation, e.g. 203.0.113.10/32)"
  type        = string
}

variable "alert_email" {
  description = "Email address for ingestion failure alerts"
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.small"
}

variable "ebs_volume_size" {
  description = "Size of the root EBS volume in GB"
  type        = number
  default     = 30
}

variable "project_repo_url" {
  description = "Git repository URL for the UCC project"
  type        = string
  default     = "https://github.com/AltumAustin/realpc_UCC_registration.git"
}
