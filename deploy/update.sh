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
