# EC2 Deployment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deploy the UCC ingestion pipeline to an EC2 instance with automated scheduling, secrets management, monitoring, and alerting.

**Architecture:** A single EC2 `t3.small` in `us-west-2` runs the Python ingestion CLI on systemd timers. Credentials come from AWS Secrets Manager via a wrapper script. CloudWatch handles logging and failure alerting via SNS email.

**Tech Stack:** Terraform (IaC), systemd (scheduling), boto3 (secrets), CloudWatch agent (logs), SNS (alerts)

---

### Task 1: Terraform Variables & Provider

**Files:**
- Create: `deploy/terraform/variables.tf`
- Create: `deploy/terraform/providers.tf`

**Step 1: Create `deploy/terraform/` directory**

Run: `mkdir -p deploy/terraform`

**Step 2: Write `variables.tf`**

```hcl
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
```

**Step 3: Write `providers.tf`**

```hcl
terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}
```

**Step 4: Verify syntax**

Run: `cd deploy/terraform && terraform fmt -check && echo "OK"`
Expected: OK (or auto-formatted)

**Step 5: Commit**

```bash
git add deploy/terraform/variables.tf deploy/terraform/providers.tf
git commit -m "Add Terraform variables and provider config for EC2 deployment"
```

---

### Task 2: Terraform Main — EC2, IAM, Security Group

**Files:**
- Create: `deploy/terraform/main.tf`

**Step 1: Write `main.tf`**

```hcl
# --- Data Sources ---

data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# --- IAM Role ---

resource "aws_iam_role" "ucc_instance" {
  name = "ucc-ingestion-ec2"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ec2.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "secrets_read" {
  name = "secrets-read"
  role = aws_iam_role.ucc_instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [aws_secretsmanager_secret.ucc_config.arn]
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ucc_instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "cloudwatch" {
  role       = aws_iam_role.ucc_instance.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_iam_instance_profile" "ucc_instance" {
  name = "ucc-ingestion-ec2"
  role = aws_iam_role.ucc_instance.name
}

# --- Security Group ---

resource "aws_security_group" "ucc_instance" {
  name        = "ucc-ingestion-ec2"
  description = "Security group for UCC ingestion EC2 instance"
  vpc_id      = var.vpc_id

  # SSH from operator IP
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.operator_ip]
    description = "SSH from operator"
  }

  # All outbound (needs to reach state APIs, Socrata, commercial provider)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "All outbound"
  }
}

# --- Secrets Manager ---

resource "aws_secretsmanager_secret" "ucc_config" {
  name        = "ucc-ingestion/config"
  description = "UCC ingestion pipeline credentials"
}

resource "aws_secretsmanager_secret_version" "ucc_config" {
  secret_id = aws_secretsmanager_secret.ucc_config.id
  secret_string = jsonencode({
    SOCRATA_APP_TOKEN        = "REPLACE_ME"
    UCC_COMMERCIAL_PROVIDER  = "baselayer"
    UCC_COMMERCIAL_API_URL   = "REPLACE_ME"
    UCC_COMMERCIAL_API_KEY   = "REPLACE_ME"
    TX_BULK_CREDENTIALS      = ""
    KY_BULK_CREDENTIALS      = ""
    WV_BULK_CREDENTIALS      = ""
    ID_BULK_CREDENTIALS      = ""
    ND_BULK_CREDENTIALS      = ""
    MN_BULK_CREDENTIALS      = ""
    AR_INA_CREDENTIALS       = ""
    IN_INBIZ_CREDENTIALS     = ""
    NY_SUBSCRIPTION_CREDENTIALS = ""
    NC_SUBSCRIPTION_CREDENTIALS = ""
    SC_BULK_CREDENTIALS      = ""
    SD_BULK_CREDENTIALS      = ""
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# --- EC2 Instance ---

resource "aws_instance" "ucc_ingestion" {
  ami                    = data.aws_ami.amazon_linux.id
  instance_type          = var.instance_type
  key_name               = var.ssh_key_name
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [aws_security_group.ucc_instance.id]
  iam_instance_profile   = aws_iam_instance_profile.ucc_instance.name

  root_block_device {
    volume_size = var.ebs_volume_size
    volume_type = "gp3"
    encrypted   = true
  }

  user_data = file("${path.module}/../setup.sh")

  tags = {
    Name    = "ucc-ingestion"
    Project = "ucc-registration"
  }
}

# --- EBS Snapshot Lifecycle ---

resource "aws_dlm_lifecycle_policy" "ebs_snapshots" {
  description        = "Daily EBS snapshots for UCC ingestion instance"
  execution_role_arn = aws_iam_role.dlm.arn
  state              = "ENABLED"

  policy_details {
    resource_types = ["INSTANCE"]

    schedule {
      name = "daily-snapshot"

      create_rule {
        interval      = 24
        interval_unit = "HOURS"
        times         = ["09:00"]
      }

      retain_rule {
        count = 7
      }

      tags_to_add = {
        SnapshotCreator = "DLM"
      }

      copy_tags = true
    }

    target_tags = {
      Name = "ucc-ingestion"
    }
  }
}

resource "aws_iam_role" "dlm" {
  name = "ucc-dlm-lifecycle"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "dlm.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "dlm" {
  role       = aws_iam_role.dlm.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSDataLifecycleManagerServiceRole"
}
```

**Step 2: Verify syntax**

Run: `cd deploy/terraform && terraform fmt && terraform validate`
Expected: "Success! The configuration is valid."

Note: `terraform validate` requires `terraform init` first. If not yet initialized, run `terraform init` then validate.

**Step 3: Commit**

```bash
git add deploy/terraform/main.tf
git commit -m "Add Terraform main: EC2, IAM, security group, secrets, EBS snapshots"
```

---

### Task 3: Terraform CloudWatch — Logs, Metric Filter, Alarm, SNS

**Files:**
- Create: `deploy/terraform/cloudwatch.tf`

**Step 1: Write `cloudwatch.tf`**

```hcl
# --- SNS Topic for Alerts ---

resource "aws_sns_topic" "ucc_alerts" {
  name = "ucc-ingestion-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.ucc_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# --- CloudWatch Log Group ---

resource "aws_cloudwatch_log_group" "ucc_ingestion" {
  name              = "/ucc-ingestion"
  retention_in_days = 30
}

# --- Metric Filter: detect ingestion failures ---

resource "aws_cloudwatch_log_metric_filter" "ingestion_failures" {
  name           = "ucc-ingestion-failures"
  log_group_name = aws_cloudwatch_log_group.ucc_ingestion.name
  pattern        = "?FAILED ?\"status=failed\" ?\"status\": \"failed\""

  metric_transformation {
    name          = "IngestionFailures"
    namespace     = "UCC/Ingestion"
    value         = "1"
    default_value = "0"
  }
}

# --- CloudWatch Alarm ---

resource "aws_cloudwatch_metric_alarm" "ingestion_failure" {
  alarm_name          = "ucc-ingestion-failure"
  alarm_description   = "Triggers when UCC ingestion run reports failure"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "IngestionFailures"
  namespace           = "UCC/Ingestion"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.ucc_alerts.arn]
  ok_actions    = [aws_sns_topic.ucc_alerts.arn]
}
```

**Step 2: Verify syntax**

Run: `cd deploy/terraform && terraform fmt && terraform validate`
Expected: "Success! The configuration is valid."

**Step 3: Commit**

```bash
git add deploy/terraform/cloudwatch.tf
git commit -m "Add Terraform CloudWatch: log group, metric filter, alarm, SNS alerts"
```

---

### Task 4: Terraform Outputs

**Files:**
- Create: `deploy/terraform/outputs.tf`

**Step 1: Write `outputs.tf`**

```hcl
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
```

**Step 2: Verify syntax**

Run: `cd deploy/terraform && terraform fmt`

**Step 3: Commit**

```bash
git add deploy/terraform/outputs.tf
git commit -m "Add Terraform outputs: instance IP, SSM/SSH commands, secret ARN"
```

---

### Task 5: Terraform tfvars example

**Files:**
- Create: `deploy/terraform/terraform.tfvars.example`
- Modify: `.gitignore` — add `*.tfvars` and `.terraform/`

**Step 1: Write `terraform.tfvars.example`**

```hcl
aws_region       = "us-west-2"
vpc_id           = "vpc-0123456789abcdef0"
subnet_id        = "subnet-0123456789abcdef0"
ssh_key_name     = "your-key-pair-name"
operator_ip      = "203.0.113.10/32"
alert_email      = "you@example.com"
instance_type    = "t3.small"
ebs_volume_size  = 30
```

**Step 2: Add Terraform ignores to `.gitignore`**

Append to the project root `.gitignore`:

```
# Terraform
deploy/terraform/.terraform/
deploy/terraform/*.tfstate
deploy/terraform/*.tfstate.backup
deploy/terraform/*.tfvars
deploy/terraform/.terraform.lock.hcl
```

**Step 3: Commit**

```bash
git add deploy/terraform/terraform.tfvars.example .gitignore
git commit -m "Add tfvars example and Terraform gitignore entries"
```

---

### Task 6: Secrets Wrapper Script

**Files:**
- Create: `deploy/fetch_secrets.py`

**Step 1: Write `fetch_secrets.py`**

This script reads credentials from AWS Secrets Manager, injects them as environment variables, and then execs the ingestion CLI. No changes needed to the existing ingestion code.

```python
#!/usr/bin/env python3
"""Fetch credentials from AWS Secrets Manager and run the ingestion CLI.

Usage:
    python3 fetch_secrets.py run --tier open_api
    python3 fetch_secrets.py status
    python3 fetch_secrets.py run --all

All arguments after the script name are passed through to `python3 -m ingestion`.
"""

import json
import os
import sys

import boto3


SECRET_ID = "ucc-ingestion/config"
REGION = os.environ.get("AWS_REGION", "us-west-2")


def fetch_secrets() -> dict:
    """Retrieve the JSON secret from AWS Secrets Manager."""
    client = boto3.client("secretsmanager", region_name=REGION)
    response = client.get_secret_value(SecretId=SECRET_ID)
    return json.loads(response["SecretString"])


def main():
    secrets = fetch_secrets()

    # Inject each key-value pair into the environment
    for key, value in secrets.items():
        if value:  # Skip empty strings
            os.environ[key] = value

    # Set production paths
    os.environ.setdefault("UCC_DB_PATH", "/opt/ucc/data/ucc_filings.db")
    os.environ.setdefault("UCC_DOWNLOAD_DIR", "/opt/ucc/data/bulk_downloads")

    # Exec the ingestion CLI with all remaining arguments
    args = sys.argv[1:]
    os.execvp("python3", ["python3", "-m", "ingestion"] + args)


if __name__ == "__main__":
    main()
```

**Step 2: Make executable**

Run: `chmod +x deploy/fetch_secrets.py`

**Step 3: Commit**

```bash
git add deploy/fetch_secrets.py
git commit -m "Add secrets wrapper: fetches Secrets Manager creds and execs ingestion CLI"
```

---

### Task 7: Systemd Service and Timer Units

**Files:**
- Create: `deploy/systemd/ucc-socrata.service`
- Create: `deploy/systemd/ucc-socrata.timer`
- Create: `deploy/systemd/ucc-bulk.service`
- Create: `deploy/systemd/ucc-bulk.timer`
- Create: `deploy/systemd/ucc-commercial.service`
- Create: `deploy/systemd/ucc-commercial.timer`

**Step 1: Create directory**

Run: `mkdir -p deploy/systemd`

**Step 2: Write `ucc-socrata.service`**

```ini
[Unit]
Description=UCC Ingestion — Socrata Open APIs (CT, CO)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=ucc
Group=ucc
WorkingDirectory=/opt/ucc/ucc-registration
ExecStart=/usr/bin/python3 /opt/ucc/deploy/fetch_secrets.py run --tier open_api
TimeoutStartSec=1800
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ucc-socrata
```

**Step 3: Write `ucc-socrata.timer`**

```ini
[Unit]
Description=Run UCC Socrata ingestion every 6 hours

[Timer]
OnCalendar=*-*-* 00,06,12,18:00:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

**Step 4: Write `ucc-bulk.service`**

```ini
[Unit]
Description=UCC Ingestion — State Bulk Subscriptions (15 states)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=ucc
Group=ucc
WorkingDirectory=/opt/ucc/ucc-registration
ExecStart=/usr/bin/python3 /opt/ucc/deploy/fetch_secrets.py run --tier state_bulk
TimeoutStartSec=3600
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ucc-bulk
```

**Step 5: Write `ucc-bulk.timer`**

```ini
[Unit]
Description=Run UCC state bulk ingestion daily at 2 AM PT

[Timer]
OnCalendar=*-*-* 09:00:00 UTC
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

Note: 2:00 AM PT = 9:00 AM UTC (during PDT) or 10:00 AM UTC (during PST). Using 09:00 UTC covers PDT. Adjust if needed.

**Step 6: Write `ucc-commercial.service`**

```ini
[Unit]
Description=UCC Ingestion — Commercial Provider (~34 states)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=ucc
Group=ucc
WorkingDirectory=/opt/ucc/ucc-registration
ExecStart=/usr/bin/python3 /opt/ucc/deploy/fetch_secrets.py run --tier commercial
TimeoutStartSec=3600
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ucc-commercial
```

**Step 7: Write `ucc-commercial.timer`**

```ini
[Unit]
Description=Run UCC commercial ingestion daily at 3 AM PT

[Timer]
OnCalendar=*-*-* 10:00:00 UTC
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

**Step 8: Commit**

```bash
git add deploy/systemd/
git commit -m "Add systemd service and timer units for 3 ingestion tiers"
```

---

### Task 8: Setup Script (EC2 User Data)

**Files:**
- Create: `deploy/setup.sh`

**Step 1: Write `setup.sh`**

This runs once on first boot via EC2 user data. It installs Python, clones the repo, creates the `ucc` user, installs the CloudWatch agent, and enables the systemd timers.

```bash
#!/bin/bash
set -euo pipefail

LOG_FILE="/var/log/ucc-setup.log"
exec > >(tee -a "$LOG_FILE") 2>&1
echo "=== UCC Ingestion Setup — $(date -u) ==="

# --- System packages ---
dnf update -y
dnf install -y python3.11 python3.11-pip git

# Make python3 point to 3.11
alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# --- Clone project ---
git clone https://github.com/AltumAustin/realpc_UCC_registration.git /opt/ucc
cd /opt/ucc/ucc-registration
pip3.11 install -r requirements.txt
pip3.11 install boto3

# --- Create ucc user ---
useradd --system --home-dir /opt/ucc --shell /usr/sbin/nologin ucc

# --- Create data directories ---
mkdir -p /opt/ucc/data/bulk_downloads
mkdir -p /opt/ucc/data/logs
chown -R ucc:ucc /opt/ucc/data

# --- Install systemd units ---
cp /opt/ucc/deploy/systemd/*.service /etc/systemd/system/
cp /opt/ucc/deploy/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload

# Enable and start timers
systemctl enable --now ucc-socrata.timer
systemctl enable --now ucc-bulk.timer
systemctl enable --now ucc-commercial.timer

# --- Install CloudWatch agent ---
dnf install -y amazon-cloudwatch-agent

cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json <<'CWCONFIG'
{
  "logs": {
    "logs_collected": {
      "journald": {
        "units": ["ucc-socrata", "ucc-bulk", "ucc-commercial"],
        "collect_list": [
          {
            "log_group_name": "/ucc-ingestion",
            "log_stream_name": "{instance_id}/{unit}",
            "retention_in_days": 30
          }
        ]
      }
    }
  }
}
CWCONFIG

systemctl enable --now amazon-cloudwatch-agent

echo "=== Setup complete — $(date -u) ==="
```

**Step 2: Make executable**

Run: `chmod +x deploy/setup.sh`

**Step 3: Commit**

```bash
git add deploy/setup.sh
git commit -m "Add EC2 setup script: Python, repo clone, ucc user, systemd, CloudWatch"
```

---

### Task 9: Update Script

**Files:**
- Create: `deploy/update.sh`

**Step 1: Write `deploy/update.sh`**

```bash
#!/bin/bash
set -euo pipefail

echo "=== UCC Ingestion Update — $(date -u) ==="

cd /opt/ucc

# Pull latest code
git pull origin main

# Update dependencies
cd ucc-registration
pip3 install -r requirements.txt

# Reload systemd units in case they changed
cp /opt/ucc/deploy/systemd/*.service /etc/systemd/system/
cp /opt/ucc/deploy/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload

# Restart timers
systemctl restart ucc-socrata.timer
systemctl restart ucc-bulk.timer
systemctl restart ucc-commercial.timer

echo "=== Update complete — $(date -u) ==="
echo ""
echo "Timer status:"
systemctl list-timers 'ucc-*' --no-pager
```

**Step 2: Make executable**

Run: `chmod +x deploy/update.sh`

**Step 3: Commit**

```bash
git add deploy/update.sh
git commit -m "Add deploy update script: git pull, pip install, restart timers"
```

---

### Task 10: Add boto3 to requirements and final verification

**Files:**
- Modify: `ucc-registration/requirements.txt`

**Step 1: Add boto3 to requirements.txt**

Append `boto3` as an optional production dependency:

```
# Core dependencies
requests>=2.28,<3

# Optional: streaming JSON parser for large files (>10MB)
# Required for memory-efficient Texas Master Unload ingestion
ijson>=3.2,<4

# Production: AWS Secrets Manager client (only needed on EC2)
boto3>=1.28
```

**Step 2: Verify project tests still pass**

Run: `cd /path/to/project && python3 -m pytest ucc-registration/tests/ -q`
Expected: `60 passed`

**Step 3: Verify Terraform syntax**

Run: `cd deploy/terraform && terraform fmt -check -recursive`
Expected: No output (all files formatted)

**Step 4: Commit**

```bash
git add ucc-registration/requirements.txt
git commit -m "Add boto3 to requirements for AWS Secrets Manager on EC2"
```

---

## Post-Deploy Checklist (manual steps after `terraform apply`)

1. **Confirm SNS subscription** — AWS sends a confirmation email to `alert_email`. Click the link.
2. **Update secrets** — Edit `ucc-ingestion/config` in the Secrets Manager console with real credentials.
3. **Verify instance** — Run `aws ssm start-session --target <instance-id>` and check:
   - `systemctl list-timers 'ucc-*'` — all 3 timers enabled
   - `journalctl -u ucc-socrata --since today` — no errors
   - `cd /opt/ucc/ucc-registration && python3 /opt/ucc/deploy/fetch_secrets.py status` — pipeline status
4. **Test a manual run** — `sudo -u ucc python3 /opt/ucc/deploy/fetch_secrets.py run --state CT`
5. **Verify CloudWatch** — Check `/ucc-ingestion` log group in the CloudWatch console for log entries.
