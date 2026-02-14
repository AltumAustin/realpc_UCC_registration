"""
Commercial provider adapter for states not covered by direct sources.

Supports pluggable backends:
  - Baselayer (baselayer.com/liens/) — API-first, all 50 states
  - First Corporate Solutions / FCS (ficoso.com) — JSON REST API
  - LexisNexis — enterprise data feed (requires custom integration)

The adapter provides a common interface; swap providers by changing
the commercial_provider setting.

~35 states are routed through this adapter. With a ≤$1M/year budget,
a nationwide daily feed contract is feasible with any major provider.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Generator, Optional

import requests

from .base import BaseAdapter
from ..config import StateSourceConfig, IngestionSettings
from ..models import UCCFiling

logger = logging.getLogger(__name__)


class CommercialProviderAdapter(BaseAdapter):
    """Fetches UCC filings from a commercial data provider API.

    The exact API contract depends on the provider. This adapter
    implements the common patterns and dispatches to provider-specific
    logic where needed.
    """

    def __init__(self, config: StateSourceConfig, settings: IngestionSettings):
        super().__init__(config, settings)
        self.provider = settings.commercial_provider
        self.api_base = settings.commercial_api_base_url
        self.api_key = settings.commercial_api_key

    def _headers(self) -> dict:
        """Build request headers with authentication."""
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.api_key:
            # Most providers use Bearer token or X-API-Key
            if self.provider == "baselayer":
                headers["Authorization"] = f"Bearer {self.api_key}"
            elif self.provider == "fcs":
                headers["Authorization"] = f"Bearer {self.api_key}"
            elif self.provider == "lexisnexis":
                headers["X-API-Key"] = self.api_key
            else:
                headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _build_url(self, state: str, endpoint: str = "filings") -> str:
        """Build the API URL for a given state and endpoint."""
        base = self.api_base.rstrip("/")

        if self.provider == "baselayer":
            return f"{base}/v1/liens/ucc/{state}/{endpoint}"
        elif self.provider == "fcs":
            return f"{base}/api/v1/ucc/{endpoint}"
        elif self.provider == "lexisnexis":
            return f"{base}/publicrecords/ucc/v1/{endpoint}"
        else:
            return f"{base}/ucc/{state}/{endpoint}"

    def _fetch_page_baselayer(self, state: str, offset: int, limit: int,
                              since: Optional[str] = None) -> list[dict]:
        """Fetch a page of filings from Baselayer API."""
        url = self._build_url(state)
        params = {"offset": offset, "limit": limit}
        if since:
            params["filed_after"] = since

        def do_request():
            resp = requests.get(
                url, params=params, headers=self._headers(),
                timeout=self.settings.request_timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("results", data.get("filings", data.get("data", [])))

        return self._retry_request(do_request)

    def _fetch_page_fcs(self, state: str, offset: int, limit: int,
                        since: Optional[str] = None) -> list[dict]:
        """Fetch a page of filings from First Corporate Solutions API."""
        url = self._build_url(state)
        params = {
            "state": state,
            "offset": offset,
            "limit": limit,
        }
        if since:
            params["filing_date_from"] = since

        def do_request():
            resp = requests.get(
                url, params=params, headers=self._headers(),
                timeout=self.settings.request_timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("records", data.get("filings", []))

        return self._retry_request(do_request)

    def _fetch_page_lexisnexis(self, state: str, offset: int, limit: int,
                               since: Optional[str] = None) -> list[dict]:
        """Fetch a page of filings from LexisNexis API."""
        url = self._build_url(state, endpoint="search")
        payload = {
            "state": state,
            "offset": offset,
            "limit": limit,
            "type": "UCC",
        }
        if since:
            payload["filingDateFrom"] = since

        def do_request():
            resp = requests.post(
                url, json=payload, headers=self._headers(),
                timeout=self.settings.request_timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("Records", data.get("results", []))

        return self._retry_request(do_request)

    def _fetch_page(self, state: str, offset: int, limit: int,
                    since: Optional[str] = None) -> list[dict]:
        """Dispatch to the correct provider's fetch method."""
        if self.provider == "baselayer":
            return self._fetch_page_baselayer(state, offset, limit, since)
        elif self.provider == "fcs":
            return self._fetch_page_fcs(state, offset, limit, since)
        elif self.provider == "lexisnexis":
            return self._fetch_page_lexisnexis(state, offset, limit, since)
        else:
            # Generic fallback
            return self._fetch_page_baselayer(state, offset, limit, since)

    def _map_record(self, raw: dict) -> UCCFiling:
        """Map a commercial provider record to a UCCFiling.

        Commercial providers generally return well-structured JSON with
        consistent field names. We normalize the common variations.
        """
        now = datetime.now(timezone.utc).isoformat()

        def get_first(*keys):
            for k in keys:
                val = raw.get(k)
                if val:
                    return str(val).strip()
            return None

        filing = UCCFiling(
            filing_number=get_first(
                "filing_number", "fileNumber", "filingNumber",
                "file_number", "documentNumber",
            ) or "UNKNOWN",
            state=self.config.abbreviation,
            filing_type=get_first(
                "filing_type", "fileType", "filingType", "type", "documentType",
            ) or "UCC",
            filing_date=get_first("filing_date", "fileDate", "filingDate", "filed_date"),
            lapse_date=get_first("lapse_date", "lapseDate", "expirationDate"),
            filing_status=get_first("status", "filing_status", "filingStatus"),
            debtor_name=get_first("debtor_name", "debtorName", "debtor"),
            debtor_address=get_first("debtor_address", "debtorAddress"),
            debtor_city=get_first("debtor_city", "debtorCity"),
            debtor_state=get_first("debtor_state", "debtorState"),
            debtor_zip=get_first("debtor_zip", "debtorZip", "debtorPostalCode"),
            debtor_organization=get_first("debtor_organization", "debtorOrganization", "debtorOrg"),
            debtor_type=get_first("debtor_type", "debtorType"),
            secured_party_name=get_first("secured_party_name", "securedPartyName", "secured_party"),
            secured_party_address=get_first("secured_party_address", "securedPartyAddress"),
            secured_party_city=get_first("secured_party_city", "securedPartyCity"),
            secured_party_state=get_first("secured_party_state", "securedPartyState"),
            secured_party_zip=get_first("secured_party_zip", "securedPartyZip", "securedPartyPostalCode"),
            collateral_description=get_first("collateral", "collateral_description", "collateralDescription"),
            original_filing_number=get_first("original_filing_number", "originalFilingNumber", "original_file_number"),
            amendment_type=get_first("amendment_type", "amendmentType"),
            source_tier="commercial",
            source_raw=json.dumps(raw),
            ingested_at=now,
        )

        # Normalize date fields to YYYY-MM-DD
        for date_field in ("filing_date", "lapse_date"):
            val = getattr(filing, date_field)
            if val and "T" in val:
                setattr(filing, date_field, val.split("T")[0])

        # Handle nested debtor/secured party objects (common in some APIs)
        if not filing.debtor_name:
            debtor_obj = raw.get("debtor", {})
            if isinstance(debtor_obj, dict):
                filing.debtor_name = debtor_obj.get("name") or debtor_obj.get("organizationName")
                filing.debtor_address = debtor_obj.get("address") or debtor_obj.get("streetAddress")
                filing.debtor_city = debtor_obj.get("city")
                filing.debtor_state = debtor_obj.get("state")
                filing.debtor_zip = debtor_obj.get("zip") or debtor_obj.get("postalCode")

        if not filing.secured_party_name:
            sp_obj = raw.get("securedParty", raw.get("secured_party", {}))
            if isinstance(sp_obj, dict):
                filing.secured_party_name = sp_obj.get("name") or sp_obj.get("organizationName")
                filing.secured_party_address = sp_obj.get("address") or sp_obj.get("streetAddress")
                filing.secured_party_city = sp_obj.get("city")
                filing.secured_party_state = sp_obj.get("state")
                filing.secured_party_zip = sp_obj.get("zip") or sp_obj.get("postalCode")

        return filing

    def fetch(self, since: Optional[str] = None) -> Generator[UCCFiling, None, None]:
        """Fetch UCC filings from the commercial provider for this state."""
        state = self.config.abbreviation
        batch_size = self.settings.batch_size
        offset = 0
        total = 0

        if not self.api_key:
            logger.error(
                "%s: no commercial provider API key configured. "
                "Set UCC_COMMERCIAL_API_KEY environment variable.",
                state,
            )
            return

        if not self.api_base:
            logger.error(
                "%s: no commercial provider API URL configured. "
                "Set UCC_COMMERCIAL_API_URL environment variable.",
                state,
            )
            return

        logger.info(
            "Starting commercial provider fetch for %s via %s%s",
            state, self.provider,
            f" since {since}" if since else " (full pull)",
        )

        while True:
            page = self._fetch_page(state, offset, batch_size, since)
            if not page:
                break

            for raw_record in page:
                yield self._map_record(raw_record)
                total += 1

            logger.info("%s: fetched %d records so far", state, total)

            if len(page) < batch_size:
                break
            offset += batch_size

        logger.info("%s: commercial fetch complete. %d total records.", state, total)

    def test_connection(self) -> bool:
        """Verify the commercial provider API is reachable."""
        if not self.api_key or not self.api_base:
            logger.error(
                "%s: commercial provider not configured (missing API key or URL)",
                self.config.abbreviation,
            )
            return False

        try:
            page = self._fetch_page(self.config.abbreviation, 0, 1)
            logger.info(
                "%s: commercial provider connection OK (%s)",
                self.config.abbreviation, self.provider,
            )
            return True
        except Exception as e:
            logger.error(
                "%s: commercial provider connection failed: %s",
                self.config.abbreviation, e,
            )
            return False
