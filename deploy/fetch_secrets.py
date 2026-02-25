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
