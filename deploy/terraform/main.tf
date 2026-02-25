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
