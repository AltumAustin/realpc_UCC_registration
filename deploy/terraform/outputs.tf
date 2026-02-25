output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.ucc_ingestion.id
}

output "instance_public_ip" {
  description = "Public IP of the EC2 instance (for SSH)"
  value       = aws_instance.ucc_ingestion.public_ip
}

output "instance_private_ip" {
  description = "Private IP of the EC2 instance"
  value       = aws_instance.ucc_ingestion.private_ip
}

output "ssm_connect_command" {
  description = "Command to connect via SSM Session Manager"
  value       = "aws ssm start-session --target ${aws_instance.ucc_ingestion.id} --region ${var.aws_region}"
}

output "ssh_connect_command" {
  description = "Command to connect via SSH"
  value       = "ssh -i ~/.ssh/${var.ssh_key_name}.pem ec2-user@${aws_instance.ucc_ingestion.public_ip}"
}

output "secret_arn" {
  description = "ARN of the Secrets Manager secret"
  value       = aws_secretsmanager_secret.ucc_config.arn
}

output "log_group" {
  description = "CloudWatch log group name"
  value       = aws_cloudwatch_log_group.ucc_ingestion.name
}

output "update_secrets_command" {
  description = "Command to update the secret values"
  value       = "aws secretsmanager put-secret-value --secret-id ucc-ingestion/config --secret-string file://secrets.json --region ${var.aws_region}"
}
