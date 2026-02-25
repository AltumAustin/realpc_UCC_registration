# EC2 Deployment Design — UCC Ingestion Pipeline

## Context

The UCC filing ingestion pipeline needs to run continuously in the cloud on a schedule, pulling data from Socrata APIs, state bulk downloads, and a commercial provider across 51 jurisdictions. The pipeline is a Python CLI tool using SQLite for storage.

## Decisions

- **Compute:** EC2 `t3.small` (2 vCPU, 2GB RAM) in `us-west-2`, in the existing VPC
- **Storage:** 30GB gp3 EBS with daily snapshots (7-day retention via Data Lifecycle Manager)
- **IaC:** Terraform
- **Secrets:** AWS Secrets Manager (single JSON secret `ucc-ingestion/config`)
- **Scheduling:** systemd timers (not cron)
- **Logging:** CloudWatch agent shipping systemd journal
- **Alerting:** CloudWatch metric filter + alarm + SNS email
- **Access:** SSM Session Manager (primary) + SSH key pair (fallback)

## Infrastructure

- EC2 instance in existing VPC/subnet (provided as Terraform variables)
- Security group: port 22 from operator IP, all outbound
- IAM role with policies: Secrets Manager read, SSM Session Manager, CloudWatch Logs
- EBS snapshots via AWS Data Lifecycle Manager, daily, 7-day retention

## Secrets & Configuration

- All credentials in a single Secrets Manager JSON secret: `ucc-ingestion/config`
- Contains: Socrata app token, commercial API key/URL, all state bulk credentials
- Thin wrapper script (`deploy/fetch_secrets.py`) reads secret via boto3, sets environment variables, then launches the ingestion CLI
- Existing `.env` approach remains for local development — no changes to ingestion code

## Scheduling

Three systemd timer/service pairs:

| Timer | Schedule | Command |
|-------|----------|---------|
| `ucc-socrata` | Every 6 hours | `python3 -m ingestion run --tier open_api` |
| `ucc-bulk` | Daily at 2:00 AM PT | `python3 -m ingestion run --tier state_bulk` |
| `ucc-commercial` | Daily at 3:00 AM PT | `python3 -m ingestion run --tier commercial` |

- Runs as dedicated `ucc` system user (no root)
- systemd captures stdout/stderr into journal

## Monitoring & Alerting

- CloudWatch agent ships systemd journal to `ucc-ingestion` log group
- Metric filter matches `FAILED` / `status=failed` in logs
- Alarm triggers on 1+ failures in 5-minute window
- SNS topic `ucc-ingestion-alerts` sends email (address provided as Terraform variable)

## Deployment & Updates

- Code at `/opt/ucc/` on the instance
- `deploy/setup.sh`: first-boot provisioning via EC2 user data (Python 3.11, pip, dependencies, ucc user, systemd timers)
- `deploy/update.sh`: git pull, pip install, restart timers
- No Docker, no CI/CD — single instance batch job

## File Layout

```
deploy/
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   └── cloudwatch.tf
├── setup.sh
├── update.sh
├── fetch_secrets.py
└── systemd/
    ├── ucc-socrata.service
    ├── ucc-socrata.timer
    ├── ucc-bulk.service
    ├── ucc-bulk.timer
    ├── ucc-commercial.service
    └── ucc-commercial.timer
```
