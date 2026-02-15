"""
Socrata SODA API adapter for states with open data portals.

Currently supports:
  - Connecticut (data.ct.gov) — dataset xfev-8smz, nightly updates
  - Colorado (data.colorado.gov) — dataset wffy-3uut, daily/weekly updates
"""

import json
import logging
from typing import Generator, Optional
from datetime import datetime, timezone

import requests

from .base import BaseAdapter
from ..config import StateSourceConfig, IngestionSettings
from ..models import UCCFiling

logger = logging.getLogger(__name__)

# Field mappings: Socrata column names → UCCFiling fields
# Verified against live API responses 2026-02-14.
CT_FIELD_MAP = {
    "id_ucc_flng_nbr": "filing_number",
    "cd_flng_type": "filing_type",
    "dt_accept": "filing_date",
    "dt_lapse": "lapse_date",
    "lien_status": "filing_status",
    "debtor_nm_bus": "debtor_name",
    "debtor_ad_str1": "debtor_address",
    "debtor_ad_city": "debtor_city",
    "debtor_ad_state": "debtor_state",
    "debtor_ad_zip": "debtor_zip",
    "sec_party_nm_bus": "secured_party_name",
    "sec_party_ad_str1": "secured_party_address",
    "sec_party_ad_city": "secured_party_city",
    "sec_party_ad_state": "secured_party_state",
    "sec_party_ad_zip": "secured_party_zip",
    "tx_lien_descript": "collateral_description",
}

CO_FIELD_MAP = {
    "transactionid": "filing_number",
    "filingtype": "filing_type",
    "filingdate": "filing_date",
    "documenttype": "collateral_description",
    "transactiontype": "amendment_type",
    "masterdocumentid": "original_filing_number",
}

STATE_FIELD_MAPS = {
    "CT": CT_FIELD_MAP,
    "CO": CO_FIELD_MAP,
}

# The Socrata date column to filter on for incremental pulls
STATE_DATE_COLUMNS = {
    "CT": "dt_accept",
    "CO": "filingdate",
}


class SocrataAdapter(BaseAdapter):
    """Fetches UCC filings from Socrata SODA API endpoints."""

    def __init__(self, config: StateSourceConfig, settings: IngestionSettings):
        super().__init__(config, settings)
        self.endpoint = config.api_endpoint
        self.field_map = STATE_FIELD_MAPS.get(config.abbreviation, {})
        self.date_column = STATE_DATE_COLUMNS.get(config.abbreviation, "filing_date")

    def _build_headers(self) -> dict:
        headers = {"Accept": "application/json"}
        if self.settings.socrata_app_token:
            headers["X-App-Token"] = self.settings.socrata_app_token
        return headers

    def _fetch_page(self, offset: int, limit: int, since: Optional[str] = None) -> list[dict]:
        """Fetch a single page of results from the SODA API."""
        params = {
            "$limit": limit,
            "$offset": offset,
            "$order": f"{self.date_column} ASC",
        }
        if since:
            params["$where"] = f"{self.date_column} >= '{since}'"

        def do_request():
            resp = requests.get(
                self.endpoint,
                params=params,
                headers=self._build_headers(),
                timeout=self.settings.request_timeout_seconds,
            )
            resp.raise_for_status()
            return resp.json()

        return self._retry_request(do_request)

    def _map_record(self, raw: dict) -> UCCFiling:
        """Map a raw Socrata record to a UCCFiling."""
        kwargs = {
            "state": self.config.abbreviation,
            "source_tier": "open_api",
            "source_raw": json.dumps(raw),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        }

        for socrata_field, filing_field in self.field_map.items():
            value = raw.get(socrata_field)
            if value is not None:
                # Normalize date fields to ISO 8601 date-only
                if filing_field in ("filing_date", "lapse_date") and "T" in str(value):
                    value = value.split("T")[0]
                kwargs[filing_field] = str(value).strip()

        # Ensure filing_number is set
        if not kwargs.get("filing_number"):
            kwargs["filing_number"] = (
                raw.get("id_ucc_flng_nbr") or raw.get("id_lien_flng_nbr")
                or raw.get("transactionid") or raw.get(":id", "UNKNOWN")
            )

        # Ensure filing_type has a value
        if not kwargs.get("filing_type"):
            kwargs["filing_type"] = (
                raw.get("cd_flng_type") or raw.get("filingtype")
                or raw.get("documenttype") or "UCC"
            )

        return UCCFiling(**kwargs)

    def fetch(self, since: Optional[str] = None) -> Generator[UCCFiling, None, None]:
        """Fetch all filings (or incremental since a date) from the SODA API.

        Paginates through the full dataset using $limit/$offset.
        """
        batch_size = self.settings.batch_size
        offset = 0
        total_fetched = 0

        logger.info(
            "Starting Socrata fetch for %s (%s)%s",
            self.config.abbreviation,
            self.endpoint,
            f" since {since}" if since else " (full pull)",
        )

        while True:
            page = self._fetch_page(offset, batch_size, since)
            if not page:
                break

            for raw_record in page:
                yield self._map_record(raw_record)
                total_fetched += 1

            logger.info(
                "%s: fetched %d records so far (page offset %d)",
                self.config.abbreviation, total_fetched, offset,
            )

            if len(page) < batch_size:
                break
            offset += batch_size

        logger.info(
            "%s: Socrata fetch complete. %d total records.",
            self.config.abbreviation, total_fetched,
        )

    def test_connection(self) -> bool:
        """Verify we can reach the SODA endpoint and get data."""
        try:
            page = self._fetch_page(offset=0, limit=1)
            logger.info("%s: Socrata connection OK", self.config.abbreviation)
            return len(page) > 0
        except Exception as e:
            logger.error(
                "%s: Socrata connection failed: %s", self.config.abbreviation, e
            )
            return False
