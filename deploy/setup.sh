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

# --- Create ucc user ---
useradd --system --home-dir /opt/ucc --shell /usr/sbin/nologin ucc

# --- Create data directories ---
mkdir -p /opt/ucc/data/bulk_downloads
mkdir -p /opt/ucc/data/logs

# Give ucc ownership of everything
chown -R ucc:ucc /opt/ucc

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
        "collect_list": [
          {
            "unit": "ucc-socrata",
            "log_group_name": "/ucc-ingestion",
            "log_stream_name": "{instance_id}/ucc-socrata",
            "retention_in_days": 30
          },
          {
            "unit": "ucc-bulk",
            "log_group_name": "/ucc-ingestion",
            "log_stream_name": "{instance_id}/ucc-bulk",
            "retention_in_days": 30
          },
          {
            "unit": "ucc-commercial",
            "log_group_name": "/ucc-ingestion",
            "log_stream_name": "{instance_id}/ucc-commercial",
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
